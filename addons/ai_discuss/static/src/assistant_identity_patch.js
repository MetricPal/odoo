import { Message } from "@mail/core/common/message";
import { ChannelMember } from "@mail/discuss/core/common/channel_member";
import { DiscussChannel } from "@mail/discuss/core/common/discuss_channel_model";

import { patch } from "@web/core/utils/patch";

/**
 * An assistant is not a person (ADR 0013): no profile card (View Profile, presence, contact details) and no voice or
 * video calls, as for OdooBot.
 */
patch(DiscussChannel.prototype, {
    get allowCalls() {
        return super.allowCalls && !this.ai_agent_id;
    },
    /** Only the avatar card openers of the chat start and the Discuss header read it. */
    get correspondentPartner() {
        return this.ai_agent_id ? undefined : super.correspondentPartner;
    },
});

patch(Message.prototype, {
    hasAuthorClickable() {
        return super.hasAuthorClickable() && !this.message.author_id?.ai_agent_partner;
    },
});

patch(ChannelMember.prototype, {
    isClickable(member) {
        return super.isClickable(member) && !member.partner_id?.ai_agent_partner;
    },
});
