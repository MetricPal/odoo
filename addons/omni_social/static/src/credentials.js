import { Component, proxy, useProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Connects a social account. Platforms with sign-in (OAuth) take the developer
 * app's ID and secret once, then a "Sign in with …" button; pasting an access
 * token stays available. Secrets are sent once and cleared from memory.
 */
export class SocialCredentials extends Component {
    static template = "omni_social.Credentials";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            token: "", account: "", secret: "", appId: "", appSecret: "",
            busy: false, manual: false, editApp: false,
        });
        onWillUnmount(() => {
            this.state.token = "";
            this.state.secret = "";
            this.state.appSecret = "";
        });
    }
    get ui() { return this.props.record.data[this.props.name] || {}; }
    get installed() { return Boolean(this.ui.installed); }
    get oauth() { return Boolean(this.ui.oauth); }
    get showApp() { return this.oauth && (!this.ui.oauth_app || this.state.editApp); }
    get showToken() { return !this.oauth || this.state.manual; }
    get webhookAllowed() {
        const data = this.props.record.data;
        return data.connected && !(data.provider === "linkedin" && data.account_kind === "person");
    }
    get accountMissing() { return this.ui.account_required && !this.state.account.trim(); }
    async _run(callback) {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            if (await this.props.record.save() === false) return;
            await callback();
        } finally { this.state.busy = false; }
    }
    async reload() { await this.props.record.model.load({ resId: this.props.record.resId }); }
    async saveApp() {
        if (!this.state.appId.trim() || !this.state.appSecret.trim()) return;
        await this._run(async () => {
            await this.orm.call("omni.social.connection", "action_oauth_app",
                [[this.props.record.resId], this.state.appId.trim(), this.state.appSecret.trim()]);
            this.state.appSecret = "";
            this.state.editApp = false;
            await this.reload();
        });
    }
    async signIn() {
        if (this.accountMissing) return;
        await this._run(async () => {
            const action = await this.orm.call("omni.social.connection", "action_oauth_start",
                [[this.props.record.resId], this.state.account.trim()]);
            await this.action.doAction(action);
        });
    }
    async connect() {
        if (!this.state.token.trim() || this.accountMissing) return;
        await this._run(async () => {
            await this.orm.call("omni.social.connection", "action_connect",
                [[this.props.record.resId], this.state.token.trim(), this.ui.account_label ? this.state.account.trim() : ""]);
            this.state.token = "";
            await this.reload();
        });
    }
    async webhook() {
        if (!this.state.secret.trim()) return;
        await this._run(async () => {
            await this.orm.call("omni.social.connection", "action_configure_webhook",
                [[this.props.record.resId], this.state.secret.trim()]);
            this.state.secret = "";
            await this.reload();
        });
    }
}
registry.category("fields").add("social_credentials", { component: SocialCredentials, supportedTypes: ["json"] });
