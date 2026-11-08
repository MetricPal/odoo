import { MessagingMenuItem } from "@mail/core/public_web/messaging_menu/messaging_menu_item";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(MessagingMenuItem.prototype, {
    /** An assistant chat not used yet shows what the assistant is for instead of an empty preview. */
    get itemPreviewText() {
        const channel = this.channel;
        if (channel?.ai_agent_id && (channel.ai_agent_paused || !channel.thread?.newestPersistentMessage)) {
            const about = channel.ai_agent_paused ? _t("Paused") : channel.ai_agent_description;
            return [channel.ai_agent_department, about].filter(Boolean).join(" · ");
        }
        return super.itemPreviewText;
    },
    get attClass() {
        const attClass = super.attClass;
        if (this.channel?.ai_agent_paused) {
            return { ...attClass, o_ai_discuss_paused: true };
        }
        return attClass;
    },
});
