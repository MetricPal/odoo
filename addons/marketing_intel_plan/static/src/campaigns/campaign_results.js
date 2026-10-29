import { Component, onWillStart, onWillUpdateProps, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/** Results tab: headline numbers, channel contribution (revenue / leads / wins), lead quality donut,
 *  CRM pipeline funnel and the comparison with an earlier campaign. Data from CRM, Sales and UTM tags. */
export class CampaignResults extends Component {
    props = useProps(standardWidgetProps);
    static template = "marketing_intel_plan.CampaignResults";

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ data: null, metric: "revenue" });
        onWillStart(() => this.load(this.props.record.resId));
        onWillUpdateProps((next) => this.load(next.record.resId));
    }

    async load(resId) {
        this.state.data = resId ? await this.orm.call("mi.plan", "get_results", [[resId]]) : null;
    }

    setMetric(metric) {
        this.state.metric = metric;
    }

    barLabel(row) {
        return this.state.metric === "revenue" ? row.revenue_label : String(row[this.state.metric]);
    }
}

registry.category("view_widgets").add("mi_campaign_results", { component: CampaignResults });
