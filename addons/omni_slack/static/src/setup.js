import { Component, proxy, useProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class SlackCredentials extends Component {
    static template = "omni_slack.Credentials";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.state = proxy({ token: "", secret: "", app: "", busy: false });
        onWillUnmount(() => { this.state.token = ""; this.state.secret = ""; });
    }
    get saved() { return this.props.record.data[this.props.name] || {}; }
    async connect() {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            if (await this.props.record.save() === false) return;
            await this.orm.call("omni.channel", "action_slack_connect",
                [[this.props.record.resId], this.state.token, this.state.secret, this.state.app]);
            this.state.token = ""; this.state.secret = "";
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
}
registry.category("fields").add("omni_slack_credentials", { component: SlackCredentials, supportedTypes: ["json"] });
