import { proxy } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";

import { MarketingPanel } from "@marketing_intel_plan/panel/panel";

/**
 * Results by channel and source (approved board 10, 2026-11-12): the panel's block keeps which channels are open
 * and which measure the donut chart shows; every number, slice, legend line and the chart's total opens its list.
 */
patch(MarketingPanel.prototype, {
    setup() {
        super.setup();
        this.cr = proxy({ measure: "leads", open: {} });
    },

    crToggle(key) {
        this.cr.open[key] = !this.cr.open[key];
    },

    crMeasure(measure) {
        this.cr.measure = measure;
    },

    /** The list behind a number: measure (clicks, leads, won, revenue, spend), row ("all", "other", a channel). */
    async crOpen(measure, row, sub = false) {
        const action = await this.orm.call("mi.panel", "open_channel_results", [measure, row, sub || false],
            { brand_id: this.state.brandId || false });
        return this.action.doAction(action);
    },

    crSliceKeydown(ev, row) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.crOpen(this.cr.measure, row);
        }
    },
});
