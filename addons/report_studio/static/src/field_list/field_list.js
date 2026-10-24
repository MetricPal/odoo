import { _t } from "@web/core/l10n/translation";
import { ModelFieldSelector } from "@web/core/model_field_selector/model_field_selector";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onWillStart, onWillUpdateProps, proxy, t, useProps } from "@odoo/owl";

/** Columns of a table box: field tags (remove with ×) plus a field picker to add one. */
export class FieldListField extends Component {
    static template = "report_studio.FieldListField";
    static components = { ModelFieldSelector };

    props = useProps({ ...standardFieldProps, resModelField: t.string().optional() });

    setup() {
        this.fieldService = useService("field");
        this.state = proxy({ labels: {} });
        onWillStart(() => this.loadLabels(this.props));
        onWillUpdateProps((next) => this.loadLabels(next));
    }

    get resModel() {
        return this.props.record.data[this.props.resModelField || "res_model"] || "";
    }

    get names() {
        return (this.props.record.data[this.props.name] || "").split(",").map((n) => n.trim()).filter(Boolean);
    }

    async loadLabels(props) {
        const model = props.record.data[props.resModelField || "res_model"];
        if (!model) {
            return;
        }
        const fields = await this.fieldService.loadFields(model);
        const labels = {};
        for (const [name, field] of Object.entries(fields)) {
            labels[name] = field.string;
        }
        this.state.labels = labels;
    }

    label(name) {
        return this.state.labels[name] || name;
    }

    write(names) {
        this.props.record.update({ [this.props.name]: names.join(", ") });
    }

    add(path) {
        const name = (path || "").split(".")[0];
        if (name && !this.names.includes(name)) {
            this.write([...this.names, name]);
        }
    }

    remove(name) {
        this.write(this.names.filter((n) => n !== name));
    }

    move(name, delta) {
        const names = [...this.names];
        const index = names.indexOf(name);
        const target = index + delta;
        if (target < 0 || target >= names.length) {
            return;
        }
        names.splice(index, 1);
        names.splice(target, 0, name);
        this.write(names);
    }

    get placeholder() {
        return _t("Add a column");
    }
}

export const fieldListField = {
    component: FieldListField,
    supportedTypes: ["char"],
    extractProps: ({ options }) => ({ resModelField: options.model }),
};

registry.category("fields").add("report_studio_field_list", fieldListField);
