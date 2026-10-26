import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

export const HEALTH = {
    on_track: { label: _t("On track"), icon: "check_circle" },
    at_risk: { label: _t("At risk"), icon: "warning" },
    off_track: { label: _t("Off track"), icon: "error" },
};

export class MarketingPortfolio extends Component {
    static template = "marketing_intel_plan.Portfolio";
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ data: null, period: "month" });
        this.health = HEALTH;
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("mi.panel", "get_portfolio", [], { period: this.state.period });
    }

    async setPeriod(period) {
        this.state.period = period;
        await this.load();
    }

    money(value) {
        return `${this.state.data.currency}${Math.round(value || 0).toLocaleString()}`;
    }

    meter(row) {
        return `width:${Math.min(row.spent_pct || 0, 100)}%`;
    }

    laneStyle(lane) {
        return `height:${lane.rows * 30 + 10}px`;
    }

    barStyle(bar) {
        return `left:${bar.left}%;width:${bar.width}%;top:${bar.row * 30 + 6}px`;
    }

    open(model, id) {
        return this.action.doAction({ type: "ir.actions.act_window", res_model: model, res_id: id,
            views: [[false, "form"]], target: "current" });
    }
}

registry.category("actions").add("marketing_intel_plan.portfolio", MarketingPortfolio);
