import { MessagingMenu } from "@mail/core/public_web/messaging_menu/messaging_menu";

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

/** "Ask an assistant" at the top of the Assistants filter (ADR 0015, approved board 20). */
patch(MessagingMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.aiActionService = useService("action");
    },
    get showAskAnAssistant() {
        return this.state().selectedFilter?.id === "chat_assistant" && this.store.self_user?.share === false;
    },
    onClickAskAnAssistant() {
        return this.aiActionService.doAction("ai_discuss.action_route_ask");
    },
});
