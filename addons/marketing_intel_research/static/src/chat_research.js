import { Composer } from "@mail/core/common/composer";
import { registerComposerAction } from "@mail/core/common/composer_actions";

import { Component, onMounted, onWillUnmount, proxy, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { isHtmlEmpty } from "@web/core/utils/html";
import { patch } from "@web/core/utils/patch";

/** Chats where Research is on, by channel id: it stays on until switched off in the + menu (owner, 2026-11-13), also
 * when the chat window is closed and opened again; the Research page button switches it on. */
export const researchMode = proxy({});

/** Characters as people count them (an emoji is one). */
export function countChars(text) {
    return [...(text || "")].length;
}

/**
 * Research in the Marketing assistant's chat (option 2a, approved boards 12.4 and 12.5; Research is a switch in the
 * composer's + menu, owner 2026-11-13): with Research on, the next
 * message is a research question for the brand and places chosen in the bar; it is saved in Insights › Research and
 * answered in the chat. Research stays on until switched off.
 */
patch(Composer.prototype, {
    setup() {
        super.setup(...arguments);
        this.miResearch = proxy({
            desk: null, loading: false, brandId: false, useWeb: true, useData: true, busy: false,
        });
        // A research question stops at the limit: typing and pasting more is refused (textarea and rich editor).
        const onBeforeInput = (ev) => this.miLimitInput(ev);
        onMounted(() => this.rootRef()?.addEventListener("beforeinput", onBeforeInput, true));
        onWillUnmount(() => this.rootRef()?.removeEventListener("beforeinput", onBeforeInput, true));
    },

    /** Characters a research question may have (1000 until the desk is read). */
    get miMax() {
        return this.miResearch.desk?.max || 1000;
    },

    /** Whether adding `added` characters (replacing the selected text) keeps the question within the limit. */
    miFits(added) {
        const selected = countChars(window.getSelection()?.toString() || "");
        return this.miCount - selected + added <= this.miMax;
    },

    miLimitInput(ev) {
        if (!this.miResearchOn || !ev.inputType?.startsWith("insert") || ev.inputType === "insertCompositionText") {
            return;
        }
        const added = ev.data ?? ev.dataTransfer?.getData("text/plain") ?? "";
        if (!this.miFits(countChars(added) || 1)) {
            ev.preventDefault();
        }
    },

    onPaste(ev) {
        if (this.miResearchOn && !this.miFits(countChars(ev.clipboardData?.getData("text/plain") || ""))) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            this.notification.add(_t("A research question has at most %s characters.", this.miMax), { type: "warning" });
            return;
        }
        return super.onPaste(...arguments);
    },

    get miResearchChat() {
        return Boolean(this.thread?.channel?.mi_research) && !this.props.composer.message;
    },

    /** On from the switch here, or from "Ask a research question" on the Research page. */
    get miResearchOn() {
        return this.miResearchChat && Boolean(researchMode[this.thread.channel.id]);
    },

    /** What the bar offers (brands, web search on, the limit), read once. */
    get miDesk() {
        if (!this.miResearch.desk && !this.miResearch.loading) {
            this.miResearch.loading = true;
            this.env.services.orm.call("mi.research", "get_desk", []).then((desk) => {
                Object.assign(this.miResearch, { desk, brandId: desk.brands[0]?.id || false, useWeb: desk.web });
            });
        }
        return this.miResearch.desk;
    },

    miToggleResearch() {
        const on = !this.miResearchOn;
        researchMode[this.thread.channel.id] = on;
    },

    get miCount() {
        return countChars(this.props.composer.composerText);
    },

    get miWebOffHint() {
        return this.miResearch.desk?.ai_manager
            ? _t("The Marketing assistant cannot search the web yet. Switch on \"Web search and reading\" on its Hermes profile (Tools and services), then Sync to Hermes.")
            : _t("The Marketing assistant cannot search the web yet, so questions look only in our data. An AI Agent manager can switch on web search.");
    },

    get placeholder() {
        if (this.miResearchOn) {
            return _t("Ask a research question…");
        }
        return super.placeholder;
    },

    async sendMessage() {
        if (this.miResearchOn) {
            return this.miSendResearch();
        }
        return super.sendMessage(...arguments);
    },

    async miSendResearch() {
        const html = this.props.composer.composerHtml;
        const { brandId, useWeb, useData, busy } = this.miResearch;
        const desk = this.miDesk;
        if (busy || isHtmlEmpty(html)) {
            return;
        }
        if (this.miCount > this.miMax) {
            this.notification.add(_t("A research question has at most %s characters.", this.miMax), { type: "warning" });
            return;
        }
        this.miResearch.busy = true;
        try {
            await this.env.services.orm.call("mi.research", "ask_in_chat", [
                this.thread.channel.id, String(html), Number(brandId) || false,
                Boolean(useWeb && desk?.web), Boolean(useData),
            ]);
            this.deleteSavedContent();
            this.clear();
        } catch (error) {
            this.notification.add(error.data?.message || error.message, { type: "danger" });
        } finally {
            this.miResearch.busy = false;
        }
    },
});

/** "Ask a research question" on the Research page (board 12.6): the assistant's chat, with Research on. */
registry.category("actions").add("mi_research_open_chat", async (env, action) => {
    const channelId = action.params?.channel_id;
    const channel = channelId && (await env.services["mail.store"]["discuss.channel"].getOrFetch(channelId));
    if (channel) {
        researchMode[channel.id] = true;
        channel.open({ focus: true });
    }
});

/** /research <question> in the Marketing assistant's chat (board 12.4). */
registry.category("discuss.channel_commands").add("research", {
    condition: ({ channel }) => Boolean(channel?.mi_research),
    help: _t("Ask a research question; the answer comes here and stays in Insights › Research"),
    methodName: "execute_command_research",
});

/** The on/off switch on the right of "Research" in the composer's + menu. */
export class ResearchSwitch extends Component {
    static template = "marketing_intel_research.ResearchSwitch";
    props = useProps({ on: t.boolean() });
}

registerComposerAction("mi-research", {
    condition: ({ owner }) => owner.miResearchChat,
    extraContentComponent: ResearchSwitch,
    extraContentComponentProps: ({ owner }) => ({ on: owner.miResearchOn }),
    icon: "search",
    name: _t("Research"),
    onSelected: ({ owner }) => owner.miToggleResearch(),
    sequence: 50,
});
