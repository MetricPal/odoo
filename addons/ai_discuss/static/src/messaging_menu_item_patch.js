import { MessagingMenuItem } from "@mail/core/public_web/messaging_menu/messaging_menu_item";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

/** An assistant chat's ⋯ menu only adds it to (or removes it from) Favorites (owner, 2026-11-09). */
const ASSISTANT_CHAT_ACTIONS = new Set(["add-to-favorites", "remove-from-favorites"]);

patch(MessagingMenuItem.prototype, {
    _computeActionsPartition() {
        const partition = super._computeActionsPartition();
        if (!this.channel?.ai_agent_id) {
            return partition;
        }
        const keep = (actions) => actions.filter((action) => ASSISTANT_CHAT_ACTIONS.has(action.id));
        return {
            ...partition,
            quick: keep(partition.quick),
            other: keep(partition.other),
            group: partition.group.map(keep).filter((actions) => actions.length),
        };
    },
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
