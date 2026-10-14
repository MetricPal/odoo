import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { _t } from "@web/core/l10n/translation";

const STATUS = {
    unchecked: { label: _t("Not verified"), color: "secondary", icon: "help" },
    ready: { label: _t("Verified"), color: "success", icon: "check_circle" },
    blocked: { label: _t("Needs attention"), color: "danger", icon: "error" },
};

class ConnectionStatus extends Component {
    static template = "ai_agent.ConnectionStatus";
    props = useProps(standardFieldProps);
    get status() { return STATUS[this.props.record.data[this.props.name]] || STATUS.unchecked; }
}
registry.category("fields").add("ai_agent_connection_status", { component: ConnectionStatus, supportedTypes: ["selection"] });
