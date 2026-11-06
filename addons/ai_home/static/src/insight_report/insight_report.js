import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Layout } from "@web/search/layout";

import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

import { useOverviewControlPanel } from "@ai_home/overview_layout/overview_layout";
import { linePoints } from "@ai_home/system_overview/system_overview";

/** Insights overview (no app) or one app's report, opened from the System overview. */
export class InsightReport extends Component {
    static template = "ai_home.InsightReport";
    static components = { Layout };
    props = useProps();

    setup() {
        useOverviewControlPanel();
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ overview: null, report: null, filter: "all" });
        onWillStart(() => this.load());
    }

    get app() {
        return this.props.action?.params?.app || "";
    }

    async load(insightId = false) {
        if (this.app) {
            this.state.report = await this.orm.call("ai.home.insight", "get_app_report", [this.app, insightId]);
        } else {
            this.state.overview = await this.orm.call("ai.home.insight", "get_insights_overview", []);
        }
    }

    get overviewRows() {
        const rows = this.state.overview?.rows || [];
        return this.state.filter === "all" ? rows : rows.filter((row) => row.priority === this.state.filter);
    }

    spark(values) {
        return linePoints(values, 84, 22, 2);
    }

    trendPoints(values) {
        return linePoints(values, 460, 150);
    }

    bandHeight(value) {
        const max = Math.max(1, ...(this.state.report?.selected.bands || []));
        return Math.round((value / max) * 120);
    }

    missingWidth(value) {
        const max = Math.max(1, ...(this.state.report?.selected.missingCounts || []).map((row) => row.count));
        return `${Math.max(2, (100 * value) / max)}%`;
    }

    openReport(app) {
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "ai_home.insight_report",
            name: _t("%s report", app),
            params: { app },
        });
    }

    select(card) {
        return this.load(card.insightId);
    }

    async openInsight(insightId) {
        const action = await this.orm.call("ai.home.insight", "action_open", [[insightId]]);
        return this.action.doAction(action);
    }

    openRecord(row) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: this.state.report.selected.model,
            res_id: row.id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("ai_home.insight_report", InsightReport);
