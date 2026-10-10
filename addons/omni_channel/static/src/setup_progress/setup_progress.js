import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class SetupProgress extends Component {
    static template = "omni_channel.SetupProgress";
    props = useProps({ ...standardFieldProps });
    get completed() {
        return Math.max(0, Math.min(5, Number(this.props.record.data[this.props.name]) || 0));
    }
}
registry.category("fields").add("omni_setup_progress", {
    component: SetupProgress,
    supportedTypes: ["integer"],
});
