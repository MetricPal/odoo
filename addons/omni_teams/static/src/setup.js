import { Component, proxy, useProps, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class TeamsCredentials extends Component {
    static template = "omni_teams.Credentials";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.state = proxy({ tenant: "", secret: "", app: "", busy: false });
        onWillUnmount(() => { this.state.secret = ""; });
    }
    get saved() { return this.props.record.data[this.props.name] || {}; }
    async connect() {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            if (await this.props.record.save() === false) return;
            await this.orm.call("omni.channel", "action_teams_connect",
                [[this.props.record.resId], this.state.app, this.state.tenant, this.state.secret]);
            this.state.secret = "";
            await this.props.record.model.load({ resId: this.props.record.resId });
        } finally { this.state.busy = false; }
    }
}
registry.category("fields").add("omni_teams_credentials", { component: TeamsCredentials, supportedTypes: ["json"] });
