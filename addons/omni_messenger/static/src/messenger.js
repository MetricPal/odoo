import { Component, proxy, useProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** Connect a Facebook Page with a Page access token (sent once, never kept in the browser). */
export class MessengerCredentials extends Component {
    static template = "omni_messenger.Credentials";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.state = proxy({ token: "", busy: false });
        onWillUnmount(() => { this.state.token = ""; });
    }
    get saved() { return this.props.record.data[this.props.name] || {}; }
    async connect() {
        if (this.state.busy || !this.state.token.trim()) return;
        this.state.busy = true;
        try {
            if (await this.props.record.save() === false) return;
            await this.orm.call("omni.channel", "action_messenger_save_connection",
                [[this.props.record.resId], this.state.token.trim()]);
            this.state.token = "";
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
}

/** Save the webhook address and app secret, then enable receiving once Meta verified it. */
export class MessengerReceiving extends Component {
    static template = "omni_messenger.Receiving";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.state = proxy({ url: this.saved.url || "", secret: "", busy: false });
        onWillUnmount(() => { this.state.secret = ""; });
    }
    get saved() { return this.props.record.data[this.props.name] || {}; }
    get needsSave() { return !this.saved.saved || Boolean(this.state.secret) || this.state.url !== this.saved.url; }
    async act() {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            if (await this.props.record.save() === false) return;
            if (this.needsSave) {
                await this.orm.call("omni.channel", "action_messenger_save_webhook",
                    [[this.props.record.resId], this.state.url, this.state.secret]);
                this.state.secret = "";
            } else {
                await this.orm.call("omni.channel", "action_setup_enable_receiving", [[this.props.record.resId]]);
            }
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
}

registry.category("fields").add("omni_messenger_credentials", { component: MessengerCredentials, supportedTypes: ["json"] });
registry.category("fields").add("omni_messenger_receiving", { component: MessengerReceiving, supportedTypes: ["json"] });
