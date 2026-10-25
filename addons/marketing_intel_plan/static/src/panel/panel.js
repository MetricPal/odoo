import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
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
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ data: null, brandId: false, tab: "upcoming", loading: true });
        this.mode = this.props.action?.params?.mode || "panel";
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("mi.panel", "get_panel", [], { brand_id: this.state.brandId || false });
        this.state.loading = false;
    }

    async onBrand(ev) {
        this.state.brandId = parseInt(ev.target.value) || false;
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

registry.category("actions").add("marketing_intel_plan.control_panel", MarketingPanel);
