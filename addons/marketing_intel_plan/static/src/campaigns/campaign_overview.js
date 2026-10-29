import { Component, onWillStart, onWillUpdateProps, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/** Campaign Overview: funnel and pillar timeline side by side (one row per pillar, same height),
 *  and the budget per month / quarter / year (target from the pillars, actual from the spend). */
export class CampaignOverview extends Component {
    props = useProps(standardWidgetProps);
    static template = "marketing_intel_plan.CampaignOverview";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ data: null, period: "month" });
        onWillStart(() => this.load(this.props.record.resId));
        onWillUpdateProps((next) => this.load(next.record.resId));
    }

    async load(resId) {
        if (!resId) {
            this.state.data = null;
            return;
        }
        this.state.data = await this.orm.call("mi.plan", "get_overview", [[resId]], { period: this.state.period });
    }

    async setPeriod(period) {
        this.state.period = period;
        await this.load(this.props.record.resId);
    }

    funnelWidth(index) {
        return 100 - index * 24;
    }

    async openPillar(pillar) {
        if (this.props.readonly && !this.props.record.resId) {
            return;
        }
        await this.action.doAction(
            { type: "ir.actions.act_window", res_model: "mi.plan.pillar", res_id: pillar.id,
              views: [[false, "form"]], target: "new", name: pillar.label },
            { onClose: () => this.load(this.props.record.resId) },
        );
    }
}

registry.category("view_widgets").add("mi_campaign_overview", { component: CampaignOverview });
