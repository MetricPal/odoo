import { Component, proxy, useProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { ChannelSetupController } from "@omni_channel/channel_setup/channel_setup";
import { formView } from "@web/views/form/form_view";

export const drafts = new WeakMap();

export class WhatsAppCredentials extends Component {
    static template = "omni_whatsapp.Credentials";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.state = proxy({ token: "", account: "", numbers: [], selected: "", busy: false, error: "" });
        drafts.set(this.props.record, this.state);
        onWillUnmount(() => {
            this.state.token = "";
            drafts.delete(this.props.record);
        });
    }
    get saved() { return this.props.record.data[this.props.name] || {}; }
    change(field, event) {
        this.state[field] = event.target.value;
        this.state.numbers = [];
        this.state.selected = "";
        this.state.error = "";
    }
    async verify() {
        if (this.state.busy) return;
        this.state.busy = true;
        this.state.error = "";
        this.state.numbers = [];
        this.state.selected = "";
        const account = this.state.account;
        const token = this.state.token;
        try {
            if (!token.trim() || !/^[1-9][0-9]{0,31}$/.test(account)) {
                this.state.error = "Enter a token and business account ID.";
                return;
            }
            const numbers = await this.orm.call("omni.channel", "action_whatsapp_verify_account",
                [[this.props.record.resId], account, token]);
            // Input changes while a request is pending must never certify new credentials.
            if (account !== this.state.account || token !== this.state.token) return;
            this.state.numbers = numbers;
            this.state.selected = numbers.length === 1 ? numbers[0].id : "";
        } finally {
            this.state.busy = false;
        }
    }
}

export class WhatsAppSetupController extends ChannelSetupController {
    static template = "omni_whatsapp.ChannelSetup";
    setup() {
        super.setup();
        this.notification = useService("notification");
    }
    async goToStep(index) {
        const record = this.model.root;
        if (record.data.is_whatsapp && this.setupState.step === 1 && index > 1 && !record.data.setup_account_id) {
            if (this.setupState.busy) return;
            const draft = drafts.get(record);
            if (!draft || draft.busy || !draft.selected || !draft.numbers.some(number => number.id === draft.selected)) {
                this.notification.add("Verify the account and choose a phone number first.", { type: "warning" });
                return;
            }
            this.setupState.busy = true;
            try {
                await this.orm.call("omni.channel", "action_whatsapp_save_connection",
                    [[record.resId], draft.account, draft.token, draft.selected]);
                draft.token = "";
                await this.model.load({ resId: record.resId });
            } finally {
                this.setupState.busy = false;
            }
        }
        return super.goToStep(index);
    }
}

registry.category("fields").add("omni_whatsapp_credentials", { component: WhatsAppCredentials, supportedTypes: ["json"] });
registry.category("views").add("omni_whatsapp_setup", { ...formView, Controller: WhatsAppSetupController });
