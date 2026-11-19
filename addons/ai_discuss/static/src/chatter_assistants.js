import { Chatter } from "@mail/chatter/web_portal_project/chatter";

import { Component, proxy, t, useOnChange, useProps } from "@odoo/owl";

import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";

/**
 * Ask an assistant about the record (ADR 0013 phase 3, approved board 11): To: the assistant, the question box,
 * Send. The question and the answer are internal notes of the chatter.
 */
export class AiChatterAsk extends Component {
    static template = "ai_discuss.ChatterAsk";
    static components = { Dropdown, DropdownItem };
    props = useProps({
        agents: t.array(),
        recordLabel: t.string(),
        resModel: t.string(),
        resId: t.number(),
        onSent: t.function(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({ agentId: this.props.agents[0]?.id, text: "", sending: false });
    }

    get agent() {
        return this.props.agents.find((agent) => agent.id === this.state.agentId) || this.props.agents[0];
    }

    get avatarUrl() {
        return `/web/image/res.users/${user.userId}/avatar_128`;
    }

    get placeholder() {
        return _t("Ask %(agent)s about this %(record)s…", {
            agent: this.agent?.name || "",
            record: this.props.recordLabel || _t("record"),
        });
    }

    choose(agent) {
        this.state.agentId = agent.id;
    }

    onKeydown(ev) {
        if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
            ev.preventDefault();
            this.send();
        }
    }

    async send() {
        const question = this.state.text.trim();
        if (!question || this.state.sending) {
            return;
        }
        this.state.sending = true;
        try {
            await this.orm.call("ai.chatter.question", "chatter_ask", [
                this.props.resModel, this.props.resId, this.agent.id, question,
            ]);
            this.state.text = "";
            this.props.onSent();
        } finally {
            this.state.sending = false;
        }
    }
}

patch(Chatter.prototype, {
    setup() {
        super.setup(...arguments);
        this.aiOrm = useService("orm");
        this.aiAssistants = proxy({ agents: [], recordLabel: "" });
        useOnChange(
            () => [this.threadModel()],
            async (model) => {
                // Only for people inside the company; the server checks again when asking.
                const result = model && this.store.self_user?.share === false
                    ? await this.aiOrm.silent.call("ai.chatter.question", "chatter_assistants", [model])
                    : { agents: [], record_label: "" };
                this.aiAssistants.agents = result.agents;
                this.aiAssistants.recordLabel = result.record_label;
            },
            { initialRun: true }
        );
    },

    onAiAsked() {
        this.toggleComposer();
        this.load(this.state.thread, ["messages"]);
    },
});

Object.assign(Chatter.components, { AiChatterAsk });
