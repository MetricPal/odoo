import { Component, useProps, proxy } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class HermesModelPicker extends Component {
    static template = "ai_agent.ModelPicker";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({ busy: false, query: "", slug: this.props.record.data.provider || this.catalog.provider || "" });
    }
    get catalog() { return this.props.record.data[this.props.name] || { providers: [] }; }
    get defaultProviderName() { return this.catalog.providers.find(p => p.slug === this.catalog.provider)?.name || this.catalog.provider || "Not reported"; }
    get providers() {
        const term = this.state.query.trim().toLowerCase();
        return this.catalog.providers.filter(p => !term || `${p.name} ${p.slug}`.toLowerCase().includes(term) || p.models.some(m => m.toLowerCase().includes(term)));
    }
    get selected() { return this.providers.find(p => p.slug === this.state.slug) || this.providers[0]; }
    get models() {
        const p = this.selected;
        if (!p) { return []; }
        const term = this.state.query.trim().toLowerCase();
        return p.models.filter(m => !term || `${p.name} ${p.slug}`.toLowerCase().includes(term) || m.toLowerCase().includes(term));
    }
    selectProvider(p) { this.state.slug = p.slug; }
    get isEngine() { return this.props.record.resModel === "ai.agent.engine"; }
    isEnabled(model) { return (this.selected?.enabled_models || []).includes(model); }
    async toggleModel(model) {
        if (this.state.busy) { return; }
        const provider = this.selected.slug;
        const enabled = !this.isEnabled(model);
        this.state.busy = true;
        try {
            if (!this.props.record.resId || await this.props.record.isDirty()) {
                this.notification.add("Save the connection before enabling models.", { type: "warning" });
                return;
            }
            await this.orm.call("ai.agent.engine", "set_model_enabled", [[this.props.record.resId], provider, model, enabled]);
            await this.props.record.load();
        } finally { this.state.busy = false; }
    }
    async selectModel(model) {
        if (this.selected.authenticated && this.props.record.data.agent_id) {
            await this.props.record.update({ provider: this.selected.slug, model, use_default: false });
        }
    }
}
registry.category("fields").add("ai_agent_model_picker", { component: HermesModelPicker, supportedTypes: ["json"] });
