import { Component, onWillStart, proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";

/** Summary strip above the campaign list: stages with arrows (like Expenses) and tiles (like Sales). */
export class CampaignDashboard extends Component {
    static template = "marketing_intel_plan.CampaignDashboard";

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ data: { stages: [], tiles: [] } });
        useBus(this.env.searchModel, "update", () => this.load());
        onWillStart(() => this.load());
    }

    async load() {
        const domain = this.env.searchModel?.domain ?? [];
        this.state.data = await this.orm.call("mi.plan", "get_campaign_dashboard", [domain]);
    }

    applyFilter(filterName) {
        const searchModel = this.env.searchModel;
        const stageNames = this.state.data.stages.map((s) => s.filter).concat(["active_plans"]);
        const isStage = stageNames.includes(filterName);
        for (const item of searchModel.query) {
            const searchItem = searchModel.searchItems[item.searchItemId];
            if (searchItem && (searchItem.name === filterName ||
                    (isStage && stageNames.includes(searchItem.name)))) {
                searchModel.toggleSearchItem(searchItem.id);
                if (searchItem.name === filterName) {
                    return;
                }
            }
        }
        const target = Object.values(searchModel.searchItems).find((s) => s.name === filterName);
        if (target) {
            searchModel.toggleSearchItem(target.id);
        }
    }
}

export class CampaignListRenderer extends ListRenderer {
    static template = "marketing_intel_plan.CampaignListRenderer";
    static components = { ...ListRenderer.components, CampaignDashboard };
}

registry.category("views").add("mi_campaign_list", { ...listView, Renderer: CampaignListRenderer });
