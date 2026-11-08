import { Component, useProps, proxy } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class HermesModelPicker extends Component {
    static template = "ai_agent.ModelPicker";
    props = useProps({ ...standardFieldProps });
    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({ busy: false, query: "", key: "", slug: this.props.record.data.provider || this.catalog.provider || "" });
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
    selectProvider(p) { this.state.slug = p.slug; this.state.key = ""; }
    /** Same wording as the connection form (approved mock 2026-11-07, boards 5 and 7). */
    status(p) {
        if (p.authenticated) { return _t("%s models · Ready", p.models.length); }
        return p.key_env ? _t("Needs a key") : _t("Sign in in Hermes");
    }
    /** Enter in the key field saves it (OWL templates cannot hold an if statement). */
    onKeyKeydown(event) {
        if (event.key === "Enter") {
            event.preventDefault();
            this.saveKey();
        }
    }

    async saveKey() {
        const key = this.state.key.trim();
        if (this.state.busy || !key) { return; }
        this.state.busy = true;
        try {
            await this.orm.call(this.props.record.resModel, "save_provider_key", [[this.props.record.resId], this.selected.slug, key]);
            this.state.key = "";
            await this.props.record.load();
        } finally { this.state.busy = false; }
    }
    get isEngine() { return this.props.record.resModel === "ai.agent.engine" || (this.props.record.resModel === "ai.agent.model.picker" && !this.props.record.data.agent_id); }
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
            await this.orm.call(this.props.record.resModel, "set_model_enabled", [[this.props.record.resId], provider, model, enabled]);
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
