import { Component, proxy, useProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class WhatsAppReceiving extends Component {
    static template = "omni_whatsapp.Receiving";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.state = proxy({ url: this.saved.url || "", secret: "", busy: false });
        onWillUnmount(() => { this.state.secret = ""; });
    }
    get saved() { return this.props.record.data[this.props.name] || {}; }
    async act() {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            // Save displayed retention values through the native record before authorizing intake.
            if (await this.props.record.save() === false) return;
            if (!this.saved.saved || this.state.secret || this.state.url !== this.saved.url) {
                await this.orm.call("omni.channel", "action_whatsapp_save_webhook",
                    [[this.props.record.resId], this.state.url, this.state.secret]);
                this.state.secret = "";
            } else {
                // The server checks the current callback handshake, secret and policy again.
                await this.orm.call("omni.channel", "action_setup_enable_receiving", [[this.props.record.resId]]);
            }
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
}

registry.category("fields").add("omni_whatsapp_receiving", {
    component: WhatsAppReceiving, supportedTypes: ["json"],
});
