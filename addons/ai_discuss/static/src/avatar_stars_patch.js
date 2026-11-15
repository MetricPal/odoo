import { DiscussAvatar } from "@mail/core/common/discuss_avatar";

import { patch } from "@web/core/utils/patch";

patch(DiscussAvatar.prototype, {
    /** An assistant's avatar: its own, or the one of a person's chat with it. */
    get isAssistant() {
        return Boolean(this.channel?.ai_agent_id || this.persona?.ai_agent_partner);
    },
});
