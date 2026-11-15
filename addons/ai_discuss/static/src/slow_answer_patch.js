import { ChannelMember } from "@mail/discuss/core/common/channel_member";
import { Typing } from "@mail/discuss/typing/common/typing";

import { onWillUnmount, proxy } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

const { DateTime } = luxon;

/** The assistant may take as long as the ERP allows a question (15 minutes) before its "typing" ends by itself. */
export const ASSISTANT_TYPING_MS = 16 * 60 * 1000;

/**
 * A slow answer is shown as a status line where "<assistant> is typing..." is, never as a message from the
 * assistant (owner, 2026-11-13): after 10 seconds "taking a bit longer", after 30 seconds "the AI service is slow
 * right now", then the minutes waited, updated every minute. It goes away when the answer (or why there is none)
 * arrives, because the assistant then stops typing.
 *
 * @param {number} seconds since the assistant started working
 * @returns {string|null} the status, or null for the usual "is typing..."
 */
export function slowAnswerStatus(seconds) {
    if (seconds < 10) {
        return null;
    }
    if (seconds < 30) {
        return _t("This is taking a bit longer than usual…");
    }
    const minutes = Math.floor(seconds / 60);
    if (minutes < 1) {
        return _t("Still working on it; the AI service is slow right now.");
    }
    return _t("Still working on it; the AI service is slow right now (%s min).", minutes);
}

/** The assistant of an assistant chat (not the person). */
function isAssistantMember(member) {
    const channel = member?.channel_id;
    return Boolean(channel?.ai_agent_id) && member.notEq(channel.self_member_id);
}

patch(ChannelMember.prototype, {
    get typingTimeoutDuration() {
        // Discuss drops another member's "typing" after 60 seconds; an assistant waiting for a slow AI service keeps
        // it until it answers (the server then turns it off).
        return isAssistantMember(this) ? ASSISTANT_TYPING_MS : super.typingTimeoutDuration;
    },
});

patch(Typing.prototype, {
    setup() {
        super.setup(...arguments);
        this.slowAnswer = proxy({ now: Date.now() });
        if (this.props.channel?.ai_agent_id) {
            const timer = setInterval(() => (this.slowAnswer.now = Date.now()), 1000);
            onWillUnmount(() => clearInterval(timer));
        }
    },

    get assistantWaitSeconds() {
        const member = this.props.channel?.ai_agent_id && this.props.channel.otherTypingMembers[0];
        if (!member || !isAssistantMember(member) || !member.is_typing_dt) {
            return null;
        }
        const now = DateTime.fromMillis(this.slowAnswer.now);
        return Math.max(0, now.diff(member.is_typing_dt).as("seconds"));
    },

    get text() {
        const seconds = this.assistantWaitSeconds;
        const status = seconds === null ? null : slowAnswerStatus(seconds);
        return status || super.text;
    },
});
