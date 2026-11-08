import { MessagingMenu } from "@mail/core/public_web/messaging_menu/messaging_menu_model";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

/**
 * The Assistants filter of Chats, after All, Unread and Group (approved mocks 2026-11-08, boards 10 and 12). The
 * server side of the filter is in ai_discuss/controllers/messaging_menu.py.
 */
patch(MessagingMenu.prototype, {
    setup() {
        super.setup(...arguments);
        const chatTab = this.chatTab;
        if (!chatTab?.compute) {
            return;
        }
        const compute = chatTab.compute;
        this.chatTab = {
            ...chatTab,
            compute() {
                const tab = compute.call(this);
                if (tab && this.store.self_user?.share === false) {
                    tab.filters = [
                        ...(tab.filters || []),
                        {
                            id: "chat_assistant",
                            text: _t("Assistants"),
                            includesChannel: (channel) => Boolean(channel.ai_agent_id),
                        },
                    ];
                }
                return tab;
            },
        };
    },
});
