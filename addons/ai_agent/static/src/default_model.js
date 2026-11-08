import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * Choose the default model of a Hermes connection (approved mock 2026-11-07, boards 5 and 6): your own key
 * (recommended for company data) or the free provider (for trying it out), and every provider Hermes offers.
 */
export class HermesDefaultModel extends Component {
    static template = "ai_agent.DefaultModel";
    props = useProps({ ...standardWidgetProps });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({
            loading: true, error: "", busy: false, data: null, choosing: false,
            slug: "", key: "", models: [], model: "", freeModel: "",
        });
        onWillStart(() => this.load());
    }

    get resId() { return this.props.record.resId; }

    async load() {
        if (!this.resId) { this.state.loading = false; return; }
        this.state.loading = true;
        this.state.error = "";
        try {
            const data = await this.orm.call("ai.agent.engine", "default_model_data", [[this.resId]]);
            this.state.data = data;
            this.state.slug = this.state.slug || data.key_providers[0]?.slug || "";
            this.state.freeModel = data.free?.models[0] || "";
            await this.loadModels();
        } catch (error) {
            this.state.error = error.data?.message || error.message || _t("Hermes could not list its providers.");
        } finally {
            this.state.loading = false;
        }
    }

    get showChooser() {
        const data = this.state.data;
        return this.state.choosing || !data || data.state !== "ready" || !data.current.model;
    }
    get selected() { return this.state.data?.providers.find((p) => p.slug === this.state.slug); }
    get providerOptions() {
        const options = [...(this.state.data?.key_providers || [])];
        if (this.selected && !options.some((p) => p.slug === this.selected.slug)) { options.push(this.selected); }
        return options;
    }
    status(provider) {
        if (provider.ready) { return { label: _t("Ready"), cls: "o_ai_status_ready" }; }
        if (provider.key_env) { return { label: _t("Needs a key"), cls: "o_ai_status_key" }; }
        return { label: _t("Sign in in Hermes"), cls: "o_ai_status_key" };
    }

    async loadModels() {
        this.state.models = [];
        this.state.model = "";
        if (!this.selected?.ready) { return; }
        const result = await this.orm.call("ai.agent.engine", "provider_models", [[this.resId], this.selected.slug]);
        this.state.models = result.models;
        this.state.model = result.recommended;
    }
    async selectProvider(slug) {
        this.state.slug = slug;
        this.state.key = "";
        await this.loadModels();
    }
    async pick(provider) {
        this.state.choosing = true;
        await this.selectProvider(provider.slug);
    }

    async use(slug, model, key) {
        if (this.state.busy) { return; }
        this.state.busy = true;
        try {
            this.state.data = await this.orm.call("ai.agent.engine", "set_default_model",
                [[this.resId], slug, model || false, key || false]);
            this.state.key = "";
            this.state.choosing = false;
            await this.props.record.load();
            this.notification.add(_t("Default model saved."), { type: "success" });
        } finally {
            this.state.busy = false;
        }
    }
    useOwnKey() {
        const provider = this.selected;
        if (!provider) { return; }
        if (!provider.ready && !this.state.key.trim()) {
            this.notification.add(_t("Enter the API key of %s.", provider.name), { type: "warning" });
            return;
        }
        return this.use(provider.slug, this.state.model, this.state.key.trim());
    }
    useFree() {
        return this.use(this.state.data.free.slug, this.state.freeModel);
    }
}

registry.category("view_widgets").add("ai_agent_default_model", { component: HermesDefaultModel });
