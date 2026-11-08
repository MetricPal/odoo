import { Dialog } from "@web/core/dialog/dialog";

import { Component, t, useProps } from "@odoo/owl";

/**
 * What each assistant can do (approved mock 2026-11-08, "Assistants A"): every assistant the user may chat with,
 * what it knows, the data it can look at and what it can propose. Ask chooses it in the assistant box.
 */
export class AssistantsDialog extends Component {
    static template = "ai_home.AssistantsDialog";
    static components = { Dialog };

    props = useProps({
        assistants: t.array(),
        selectedId: t.string().optional(""),
        canManage: t.boolean().optional(false),
        onAsk: t.function(),
        onManage: t.function(),
        close: t.function(),
    });

    isChosen(assistant) {
        return !assistant.paused && `${assistant.id}` === this.props.selectedId;
    }

    ask(assistant) {
        this.props.onAsk(assistant);
        this.props.close();
    }

    manage() {
        this.props.close();
        this.props.onManage();
    }
}
