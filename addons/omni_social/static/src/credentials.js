import { Component, proxy, useProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
export class SocialCredentials extends Component {
    static template = "omni_social.Credentials";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.state = proxy({ token: "", account: "", secret: "", busy: false });
        onWillUnmount(() => { this.state.token = ""; this.state.secret = ""; });
    }
    get linkedInPage() { return this.props.record.data.provider === "linkedin" && this.props.record.data.account_kind === "organization"; }
    get installed() { return ["instagram", "linkedin"].includes(this.props.record.data.provider); }
    async webhook() {
        if (this.state.busy || !this.state.secret.trim()) return;
        this.state.busy = true;
        try {
            if (await this.props.record.save() === false) return;
            await this.orm.call("omni.social.connection", "action_configure_webhook", [[this.props.record.resId], this.state.secret.trim()]);
            this.state.secret = "";
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
    async connect() {
        if (this.state.busy || !this.state.token.trim()) return;
        this.state.busy = true;
        try {
            if (await this.props.record.save() === false) return;
            await this.orm.call("omni.social.connection", "action_connect",
                [[this.props.record.resId], this.state.token.trim(), this.linkedInPage ? this.state.account.trim() : ""]);
            this.state.token = "";
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
}
registry.category("fields").add("social_credentials", { component: SocialCredentials, supportedTypes: ["json"] });
