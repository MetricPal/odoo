import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { patch } from "@web/core/utils/patch";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { SearchModel } from "@web/search/search_model";
import { WithSearch } from "@web/search/with_search/with_search";

import { ExecutiveOverview } from "./executive";

/** Filters of which only one is on at a time: picking one turns the others of its kind off. */
export const SINGLE_CHOICE = ["period_", "channel_", "team_"];

function escape(text) {
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

/** The search view of the overview: Brand in the box; Period, Channel, Team and Compare in Filters. */
export function executiveSearchArch({ channels, teams }) {
    const filter = (name, label) => `<filter name="${escape(name)}" string="${escape(label)}" domain="[]"/>`;
    const parts = [
        '<search>',
        '<field name="brand_id" string="Brand"/>',
        filter("period_month", _t("This month")),
        filter("period_quarter", _t("This quarter")),
        filter("period_year", _t("This year")),
        "<separator/>",
        ...channels.map((channel) => filter(`channel_${channel.id}`, channel.label)),
    ];
    if (teams.length) {
        parts.push("<separator/>", ...teams.map((team) => filter(`team_${team.id}`, team.label)));
    }
    parts.push("<separator/>", filter("compare", _t("Compare periods")), "</search>");
    return parts.join("");
}

export class ExecutiveSearchModel extends SearchModel {
    hideCustomFilter = true;

    toggleSearchItem(searchItemId) {
        const item = this.searchItems[searchItemId];
        const prefix = SINGLE_CHOICE.find((p) => item?.name?.startsWith(p));
        const turningOn = !this.query.some((q) => q.searchItemId === searchItemId);
        if (prefix && turningOn) {
            this.query = this.query.filter((q) => {
                const other = this.searchItems[q.searchItemId];
                return !(other?.type === "filter" && other.name?.startsWith(prefix));
            });
        }
        return super.toggleSearchItem(searchItemId);
    }
}

/** The report reads only its own filters, so the search box does not suggest a custom filter either. */
patch(SearchBar.prototype, {
    async computeState(options = {}) {
        await super.computeState(options);
        if (this.env.searchModel?.hideCustomFilter) {
            const index = this.items.findIndex((item) => item.isAddCustomFilterButton);
            if (index >= 0) {
                this.items.splice(index, 1);
            }
        }
    },
});

/** Insights › Reports › Executive overview: Odoo's search around the page, as on Campaigns. */
export class ExecutiveOverviewAction extends Component {
    static template = "marketing_intel_reports.ExecutiveOverviewAction";
    static components = { WithSearch, ExecutiveOverview };
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ options: null });
        onWillStart(async () => {
            this.state.options = await this.orm.call("mi.report.executive", "get_filter_options", []);
        });
    }

    get withSearchProps() {
        return {
            resModel: "mi.plan",
            SearchModel: ExecutiveSearchModel,
            searchViewId: false,
            searchViewArch: executiveSearchArch(this.state.options),
            searchMenuTypes: ["filter", "favorite"],
            loadIrFilters: true,
            context: {
                search_default_period_quarter: 1,
                search_default_compare: 1,
                ...(this.props.action?.context || {}),
            },
        };
    }
}

registry.category("actions").add("marketing_intel_reports.executive", ExecutiveOverviewAction, { force: true });
