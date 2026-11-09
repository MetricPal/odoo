import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { CheckboxItem } from "@web/core/dropdown/checkbox_item";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { WithSearch } from "@web/search/with_search/with_search";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

const GROUP_ORDER = ["out", "scheduled", "waiting", "fix", "todo"];
export const GROUP_LABELS = {
    out: _t("Sent"),
    scheduled: _t("Scheduled"),
    waiting: _t("Waiting for approval"),
    fix: _t("Needs fixing"),
    todo: _t("Being prepared"),
};

/** SVG polyline points for a small trend line (100 x 32 box). */
export function sparkline(values, width = 100, height = 32) {
    if (!values || values.length < 2) {
        return "";
    }
    const max = Math.max(...values, 1);
    const step = width / (values.length - 1);
    return values
        .map((value, index) => `${(index * step).toFixed(1)},${(height - 2 - (value / max) * (height - 4)).toFixed(1)}`)
        .join(" ");
}

/** Group timeline events under day headings. */
export function groupByDay(events) {
    const groups = [];
    const today = luxon.DateTime.local().startOf("day");
    for (const event of events) {
        const when = event.all_day ? luxon.DateTime.fromSQL(event.at) : deserializeDateTime(event.at);
        const day = when.startOf("day");
        const diff = Math.round(day.diff(today, "days").days);
        const label =
            diff === 0 ? _t("Today") : diff === 1 ? _t("Tomorrow") : diff === -1 ? _t("Yesterday") : day.toFormat("ccc d LLL");
        let group = groups.find((g) => g.key === day.toISODate());
        if (!group) {
            group = { key: day.toISODate(), label, events: [] };
            groups.push(group);
        }
        group.events.push({ ...event, time: event.all_day ? "" : when.toFormat("HH:mm") });
    }
    return groups;
}

export class MarketingPanel extends Component {
    static template = "marketing_intel_plan.Panel";
    static components = { Layout, SearchBar, CheckboxItem };
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ data: null, brandId: false, tab: "upcoming", loading: true, editing: false, draft: [],
            explain: {} });
        this.notification = useService("notification");
        // The brand comes from Odoo's search bar (searching campaigns by brand).
        this.searchModel = this.env.searchModel;
        onWillStart(async () => {
            this.state.brandId = await this.searchedBrand();
            await this.load();
        });
        useBus(this.searchModel, "update", async () => {
            const brandId = await this.searchedBrand();
            if (brandId !== this.state.brandId) {
                this.state.brandId = brandId;
                await this.load();
            }
        });
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("mi.panel", "get_panel", [], { brand_id: this.state.brandId || false });
        this.state.loading = false;
    }

    // -- control panel: summary and the search box (views and brands) --------------------------------------------
    get summary() {
        const { counts, flows } = this.state.data;
        const plural = (n, one, many) => (n === 1 ? one : many).replace("%s", n);
        return [
            plural(counts.active, _t("%s active campaign"), _t("%s active campaigns")),
            plural(flows.length, _t("%s workflow"), _t("%s workflows")),
            plural(counts.brands, _t("%s brand"), _t("%s brands")),
        ].join(" · ");
    }

    /** The views the panel offers: the user's own (when saved) and one per role. */
    get views() {
        const layout = this.state.data.layout;
        const views = layout.has_mine ? [{ key: "mine", label: _t("My view") }] : [];
        return views.concat(layout.roles.map((role) => ({ key: role.key, label: _t("%s view", role.label) })));
    }

    /**
     * The brand searched in the search bar: a brand picked from the suggestions, or the first brand whose name
     * matches the typed text. The panel shows one brand at a time (all brands when nothing is searched).
     */
    async searchedBrand() {
        const leaves = this.searchModel.domain.filter((leaf) => Array.isArray(leaf) && leaf[0] === "brand_id");
        for (const [, operator, value] of leaves) {
            if (typeof value === "number") {
                return value;
            }
            const ids = await this.orm.search("mi.brand", [["name", operator, value]], { limit: 1, order: "name" });
            if (ids.length) {
                return ids[0];
            }
        }
        return false;
    }

    // -- customising -------------------------------------------------------------------------------------------
    get blocks() {
        return this.state.editing ? this.state.draft : this.state.data.layout.blocks;
    }

    get missingBlocks() {
        const used = new Set(this.state.draft.map((b) => b.key));
        return this.state.data.layout.catalogue.filter((c) => !used.has(c.key));
    }

    blockLabel(block) {
        if (block.key === "report") {
            const box = this.state.data.layout.boxes.find((b) => b.id === block.report_block_id);
            return box ? `${box.report} › ${box.title}` : _t("Report box");
        }
        return this.state.data.layout.catalogue.find((c) => c.key === block.key)?.label || block.key;
    }

    startEdit() {
        this.state.draft = this.state.data.layout.blocks.map((b) => ({ ...b }));
        this.state.editing = true;
    }

    cancelEdit() {
        this.state.editing = false;
    }

    move(index, step) {
        const target = index + step;
        if (target < 0 || target >= this.state.draft.length) {
            return;
        }
        const blocks = [...this.state.draft];
        [blocks[index], blocks[target]] = [blocks[target], blocks[index]];
        this.state.draft = blocks;
    }

    toggleWidth(index) {
        const blocks = [...this.state.draft];
        blocks[index] = { ...blocks[index], width: blocks[index].width === "full" ? "half" : "full" };
        this.state.draft = blocks;
    }

    remove(index) {
        this.state.draft = this.state.draft.filter((_b, i) => i !== index);
    }

    addBlock(ev) {
        const value = ev.target.value;
        ev.target.value = "";
        if (!value) {
            return;
        }
        if (value.startsWith("report:")) {
            const id = parseInt(value.split(":")[1]);
            if (!this.state.draft.some((b) => b.key === "report" && b.report_block_id === id)) {
                this.state.draft = [...this.state.draft, { key: "report", report_block_id: id, width: "half" }];
            }
        } else {
            this.state.draft = [...this.state.draft, { key: value, width: ["kpis", "campaigns", "flows"].includes(value) ? "full" : "half" }];
        }
    }

    async save(scope, role = false) {
        const blocks = this.state.draft.map(({ key, width, report_block_id }) => ({ key, width, report_block_id }));
        await this.orm.call("mi.panel.layout", "save_layout", [blocks], { scope, role });
        this.state.editing = false;
        this.notification.add(scope === "role" ? _t("Saved for the role.") : _t("Saved as your view."), { type: "success" });
        await this.load();
    }

    async saveRole(ev) {
        const role = ev.target.value;
        ev.target.value = "";
        if (role) {
            await this.save("role", role);
        }
    }

    async setView(key) {
        if (key === this.state.data.layout.view) {
            return;
        }
        await this.orm.call("mi.panel.layout", "choose_view", [key]);
        this.state.editing = false;
        await this.load();
    }

    get brandGroups() {
        const groups = {};
        for (const brand of this.state.data.brands) {
            (groups[brand.group || ""] ||= []).push(brand);
        }
        return Object.entries(groups).map(([name, brands]) => ({ name, brands }));
    }

    get timeline() {
        const events = this.state.data.timeline[this.state.tab] || [];
        return groupByDay(events);
    }

    spark(values) {
        return sparkline(values);
    }

    formatValue(kpi) {
        const value = Math.round(kpi.value || 0).toLocaleString();
        return kpi.money ? `${this.state.data.currency}${value}` : value;
    }

    segments(row) {
        const total = Math.max(row.total, 1);
        return GROUP_ORDER.filter((key) => row.groups[key]).map((key) => ({
            key,
            count: row.groups[key],
            width: `${(100 * row.groups[key]) / total}%`,
            label: GROUP_LABELS[key],
        }));
    }

    /** "Explain this": the assistant reads the block's numbers for the viewer's role (ADR 0016, board 6.x). */
    async explain(key) {
        this.state.explain[key] = { waiting: true, text: "" };
        let runId;
        try {
            runId = await this.orm.call("mi.panel", "explain_block", [key], { brand_id: this.state.brandId || false });
        } catch (error) {
            this.state.explain[key] = { waiting: false, text: error.data?.message || _t("The assistant could not be asked.") };
            return;
        }
        for (let round = 0; round < 90; round++) {
            await new Promise((resolve) => setTimeout(resolve, 2000));
            const result = await this.orm.call("mi.panel", "explain_result", [runId]);
            if (result.done) {
                this.state.explain[key] = { waiting: false, text: result.text };
                return;
            }
        }
        this.state.explain[key] = { waiting: false, text: _t("The answer is taking longer than usual. Try again later.") };
    }

    open(model, resId) {
        if (!model || !resId) {
            return;
        }
        return this.action.doAction({ type: "ir.actions.act_window", res_model: model, res_id: resId,
            views: [[false, "form"]], target: "current" });
    }

    openKpi(kpi) {
        const map = {
            leads: "crm.crm_lead_all_leads",
            goals: "marketing_intel_plan.action_goals",
            budget: "marketing_intel_plan.action_campaign_results",
            revenue: "marketing_intel_plan.action_campaign_results",
            sent: "marketing_intel_plan.action_campaign_results",
            clicks: "marketing_intel_plan.action_campaign_results",
        };
        if (map[kpi.key]) {
            return this.action.doAction(map[kpi.key]).catch(() =>
                this.action.doAction("marketing_intel_plan.action_campaign_results"));
        }
    }

    async go(xmlid, context = {}) {
        try {
            return await this.action.doAction(xmlid, {
                additionalContext: { ...context, default_brand_id: this.state.brandId || undefined } });
        } catch {
            return this.action.doAction("marketing_intel_plan.action_plans");
        }
    }

    newCampaign() {
        return this.action.doAction({ type: "ir.actions.act_window", res_model: "mi.plan", views: [[false, "form"]],
            target: "current", context: { default_brand_id: this.state.brandId || undefined } });
    }
}

/** The client action: Odoo's search (campaigns, searched by brand) around the panel. */
export class MarketingPanelAction extends Component {
    static template = "marketing_intel_plan.PanelAction";
    static components = { WithSearch, MarketingPanel };
    props = useProps();

    get withSearchProps() {
        return {
            resModel: "mi.plan",
            searchViewId: false,
            searchViewArch: '<search><field name="brand_id"/></search>',
            searchMenuTypes: ["favorite"],
            loadIrFilters: true,
            context: this.props.action?.context || {},
        };
    }
}

registry.category("actions").add("marketing_intel_plan.control_panel", MarketingPanelAction);
