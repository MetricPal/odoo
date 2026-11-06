import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";

import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

import { useOverviewControlPanel } from "@ai_home/overview_layout/overview_layout";

export const PERIODS = [
    ["today", _t("Today")],
    ["7", _t("7 days")],
    ["30", _t("30 days")],
];

/** SVG polyline points for a series, scaled into a box. */
/** Bars for the 24 hourly request counts, 1280 x 116 drawing area. */
export function trafficBars(hours, width = 1280, height = 116) {
    const max = Math.max(1, ...hours.map((hour) => hour.value));
    const step = (width - 16) / Math.max(1, hours.length);
    return hours.map((hour, index) => {
        const barHeight = Math.round(((height - 8) * hour.value) / max);
        return { ...hour, x: Math.round(8 + index * step + (step - 40) / 2), y: height - barHeight, height: barHeight };
    });
}

export function linePoints(values, width, height, pad = 8) {
    const max = Math.max(1, ...values);
    const step = values.length > 1 ? (width - 2 * pad) / (values.length - 1) : 0;
    return values.map((value, i) => `${(pad + i * step).toFixed(1)},${(height - pad - (value / max) * (height - 2 * pad)).toFixed(1)}`).join(" ");
}

export class SystemOverview extends Component {
    static template = "ai_home.SystemOverview";
    static components = { Layout };
    props = useProps();

    setup() {
        useOverviewControlPanel();
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ period: "7", data: null, loading: true });
        onWillStart(() => this.load());
    }

    get periods() {
        return PERIODS.map(([key, label]) => ({ key, label }));
    }

    async load() {
        this.state.loading = true;
        this.state.data = await this.orm.call("ai.home.item", "get_system_overview", [this.state.period]);
        this.state.loading = false;
    }

    setPeriod(key) {
        this.state.period = key;
        return this.load();
    }

    get seriesValues() {
        return (this.state.data?.series || []).map((point) => point.value);
    }

    get seriesPoints() {
        return linePoints(this.seriesValues, 1280, 180);
    }

    get trafficBars() {
        return trafficBars(this.state.data?.traffic || []);
    }

    get trafficTicks() {
        return this.trafficBars.filter((bar, index) => index % 3 === 0);
    }

    get seriesLabels() {
        const series = this.state.data?.series || [];
        const every = Math.max(1, Math.ceil(series.length / 7));
        return series
            .map((point, index) => ({
                ...point,
                x: 8 + (index * 1264) / Math.max(1, series.length - 1),
                anchor: index === 0 ? "start" : index === series.length - 1 ? "end" : "middle",
            }))
            .filter((point, index) => index % every === 0 || index === series.length - 1);
    }

    spark(values) {
        return linePoints(values, 84, 22, 2);
    }

    barWidth(row, part) {
        const max = Math.max(1, ...(this.state.data?.activities || []).map((r) => r.late + r.today + r.planned));
        return `${(100 * row[part]) / max}%`;
    }

    async openApp(row) {
        if (row.hasReport) {
            return this.action.doAction({
                type: "ir.actions.client",
                tag: "ai_home.insight_report",
                name: _t("%s report", row.app),
                params: { app: row.app },
            });
        }
        const action = await this.orm.call("ai.home.item", "open_overview_app", [row.model]);
        return this.action.doAction(action);
    }

    openAllInsights() {
        return this.action.doAction("ai_home.action_insights_overview");
    }

    async openCheck(row) {
        const action = await this.orm.call("ai.home.insight", "action_open", [[row.insightId]]);
        return this.action.doAction(action);
    }
}

registry.category("actions").add("ai_home.system_overview", SystemOverview);
