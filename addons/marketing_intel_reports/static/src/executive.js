import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

const CIRCLE = 2 * Math.PI * 50;
const PERIODS = [
    ["month", "This month"],
    ["quarter", "This quarter"],
    ["year", "This year"],
];

/**
 * Insights › Reports › Executive overview (boards 17.1 to 17.3): the numbers of the Head of department's or the
 * Senior's campaigns for a month, quarter or year. Everything comes from one server call; the page only draws it.
 */
export class ExecutiveOverview extends Component {
    static template = "marketing_intel_reports.ExecutiveOverview";
    static components = { Layout };
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS;
        this.state = proxy({ data: null, period: "quarter", brand: 0, channel: "", team: 0, compare: true });
        onWillStart(() => this.load());
    }

    async load() {
        const { period, brand, channel, team, compare } = this.state;
        this.state.data = await this.orm.call("mi.report.executive", "get_overview", [], {
            period, brand_id: brand || false, channel: channel || false, team: team || false, compare,
        });
    }

    async setPeriod(period) {
        this.state.period = period;
        await this.load();
    }
    async onFilter(name, ev) {
        const value = ev.target.value;
        this.state[name] = name === "channel" ? value : Number(value);
        await this.load();
    }
    async onCompare(ev) {
        this.state.compare = ev.target.checked;
        await this.load();
    }
    print() {
        window.print();
    }
    open(planId) {
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: "mi.plan", res_id: planId, views: [[false, "form"]],
        });
    }

    // ------------------------------------------------------------------ the month-by-month chart

    get trend() {
        const trend = this.state.data.trend;
        const count = trend.labels.length;
        const top = this.niceTop(trend.top);
        const group = 500 / count;
        const width = Math.min(44, group * 0.3);
        const y = (value) => 195 - (value / top) * 175;
        const bars = [];
        trend.labels.forEach((label, i) => {
            const centre = 48 + group * (i + 0.5);
            const spend = trend.spend[i] || 0;
            const revenue = trend.revenue[i] || 0;
            bars.push({
                label, x: centre, text: label,
                spend: { x: centre - width - 2, y: y(spend), w: width, h: 195 - y(spend), value: trend.spend_label[i] },
                revenue: trend.revenue.length ? { x: centre + 2, y: y(revenue), w: width, h: 195 - y(revenue), value: trend.revenue_label[i] } : null,
            });
        });
        const grid = [1, 2, 3, 4].map((step) => ({ y: y((top / 5) * step), text: this.short((top / 5) * step) }));
        return { bars, grid, leads: trend.leads.join(" · "), hasRevenue: trend.revenue.length > 0 };
    }
    niceTop(value) {
        const power = Math.pow(10, Math.floor(Math.log10(Math.max(value, 1))));
        const unit = value / power;
        const step = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10;
        return step * power;
    }
    short(value) {
        return value >= 1000 ? `${Math.round(value / 100) / 10}k` : String(Math.round(value));
    }

    // ------------------------------------------------------------------ the donut

    get donut() {
        const channels = this.state.data.channels;
        let offset = 0;
        const segments = [];
        for (const row of channels.rows) {
            const length = channels.total ? (row.share_value / channels.total) * CIRCLE : 0;
            if (length > 0) {
                segments.push({ color: row.color, dash: `${length.toFixed(1)} ${CIRCLE.toFixed(1)}`, offset: -offset.toFixed(1) });
            }
            offset += length;
        }
        const text = channels.rows.map((row) => `${row.label} ${row.share}%`).join(", ");
        return { segments, text };
    }

    funnelBar(row) {
        return `width:${Math.max(row.width, row.count ? 6 : 0)}%;background:${FUNNEL_COLORS[Math.min(this.state.data.funnel.rows.indexOf(row), FUNNEL_COLORS.length - 1)]}`;
    }
}

const FUNNEL_COLORS = ["#145045", "#1d6b5a", "#4f8a78", "#7fa99a", "#2e8b6e"];

registry.category("actions").add("marketing_intel_reports.executive", ExecutiveOverview);
