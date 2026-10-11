import { Component, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { ReferenceField, referenceField } from "@web/views/fields/reference/reference_field";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { TextField, textField } from "@web/views/fields/text/text_field";

export class TemplateFormat extends Component {
    static template = "omni_template.Format";
    props = useProps(standardFieldProps);
    get choices() { return this.props.record.data.format_choices || []; }
    change(event) { return this.props.record.update({ [this.props.name]: event.target.value }); }
}
registry.category("fields").add("omni_template_format", {
    component: TemplateFormat, supportedTypes: ["selection"],
    fieldDependencies: [{ name: "format_choices", type: "json" }],
});

export class TemplateBody extends TextField {
    static template = "omni_template.Body";
    get minimumHeight() { return 224; }
    get count() { return this.value.length; }
    get canFormat() { return ["whatsapp", "telegram", "slack", "teams", "discord"].includes(this.props.record.data.channel_code); }
    async format(style) {
        const input = this.textareaRef();
        const selection = input.value.slice(input.selectionStart, input.selectionEnd) || "text";
        const channel = this.props.record.data.channel_code;
        const mark = style === "bold" ? (["whatsapp", "slack"].includes(channel) ? "*" : "**") : "_";
        const replacement = channel === "telegram" ? `<${style === "bold" ? "b" : "i"}>${selection}</${style === "bold" ? "b" : "i"}>` : mark + selection + mark;
        input.setRangeText(replacement, input.selectionStart, input.selectionEnd, "end");
        input.dispatchEvent(new InputEvent("input"));
        input.dispatchEvent(new KeyboardEvent("keydown"));
        input.focus();
    }
}
registry.category("fields").add("omni_template_body", {
    ...textField, component: TemplateBody,
    fieldDependencies: [{ name: "channel_code", type: "char" }],
});

export class TemplateOptional extends Component {
    static template = "omni_template.Optional";
    props = useProps(standardFieldProps);
    get label() { return this.props.record.fields[this.props.name].string; }
    toggle() { return this.props.record.update({ [this.props.name]: !this.props.record.data[this.props.name] }); }
}
registry.category("fields").add("omni_template_optional", {component: TemplateOptional, supportedTypes: ["boolean"]});

// Reuse native record search without granting read access to technical ir.model records.
export class TemplateRecord extends ReferenceField {
    getModelName() { return this.props.record.data.model_name; }
    updateM2O(value) {
        return this.props.record.update({ [this.props.name]: value && {resModel: this.getModelName(), resId: value.id, displayName: value.display_name} });
    }
}
registry.category("fields").add("omni_template_record", {
    ...referenceField, component: TemplateRecord,
    extractProps: (...args) => ({ ...referenceField.extractProps(...args), hideModel: true, modelField: undefined }),
    fieldDependencies: [{ name: "model_name", type: "selection" }],
});
