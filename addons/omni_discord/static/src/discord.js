import { Component, proxy, useProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** Connect a Discord bot with its token (sent once, never kept in the browser). */
export class DiscordCredentials extends Component {
    static template = "omni_discord.Credentials";
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
            await this.orm.call("omni.channel", "action_discord_save_connection",
                [[this.props.record.resId], this.state.token.trim()]);
            this.state.token = "";
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
}

/** Relay target, server channels to read, and the command that runs the relay. */
export class DiscordReceiving extends Component {
    static template = "omni_discord.Receiving";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.state = proxy({ url: this.saved.url || "", channels: this.saved.channels || "", busy: false });
    }
    get saved() { return this.props.record.data[this.props.name] || {}; }
    get needsSave() { return this.state.url !== (this.saved.url || "") || this.state.channels !== (this.saved.channels || ""); }
    async act() {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            if (await this.props.record.save() === false) return;
            if (this.needsSave || !this.saved.url) {
                await this.orm.call("omni.channel", "action_discord_save_receiving",
                    [[this.props.record.resId], this.state.url, this.state.channels]);
            } else {
                await this.orm.call("omni.channel", "action_setup_enable_receiving", [[this.props.record.resId]]);
            }
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
}

registry.category("fields").add("omni_discord_credentials", { component: DiscordCredentials, supportedTypes: ["json"] });
registry.category("fields").add("omni_discord_receiving", { component: DiscordReceiving, supportedTypes: ["json"] });
