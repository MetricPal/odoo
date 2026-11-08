import { Thread } from "@mail/core/common/thread";

import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

patch(Thread.prototype, {
    get startMessageSubtitle() {
        const channel = this.channel;
        if (channel?.channel_type === "chat" && channel.ai_agent_id) {
            return _t(
                "This is the start of your direct chat with %(name)s, the %(department)s assistant. It answers with what you may see, and changes need your approval.",
                { name: channel.displayName, department: channel.ai_agent_department }
            );
        }
        return super.startMessageSubtitle;
    },
});
