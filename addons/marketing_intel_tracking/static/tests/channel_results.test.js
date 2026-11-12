import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { Component, proxy, useProps, xml } from "@odoo/owl";
import { getTemplate } from "@web/core/templates";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";

defineMailModels();

/** A plain click on an SVG shape (hoot's pointer simulation does not support SVG elements). */
async function clickSvg(selector, index = 0) {
    document.querySelectorAll(selector)[index].dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await animationFrame();
}

const SLICE = "M100,20 A80,80 0 0 1 180,100 L146.4,100 A46.4,46.4 0 0 0 100,53.6 Z";
const RESULTS = {
    period: "Q4 2026", crm: true, brand_id: false,
    can_open: { clicks: true, leads: true, won: true, revenue: true, spend: true },
    rows: [
        { key: "email", label: "Email", color: "#71639e", clicks: 4210, leads: 312, won: 41, revenue: "RM 121,000",
          revenue_value: 121000, spend: "RM 8,000", cpl: "RM 26", roi: "15.1×", roi_bad: false, share: 32,
          sources: [{ label: "Spring offer", sub: ["reference", "mailing.mailing,5"], clicks: 2980, leads: 201, won: 29,
                      revenue: "RM 84,000" }] },
        { key: "social", label: "Social Media", color: "#d9822b", clicks: 6820, leads: 273, won: 30,
          revenue: "RM 94,500", revenue_value: 94500, spend: "RM 103,700", cpl: "RM 380", roi: "0.9×", roi_bad: true,
          share: 28, sources: [] },
    ],
    other: { key: "other", label: "Not from a marketing link", color: "#b9bfc6", leads: 142, won: 22,
             revenue: "RM 61,000", revenue_value: 61000, share: 15 },
    totals: { clicks: 11030, leads: 727, won: 93, revenue: "RM 276,500", spend: "RM 111,700", cpl: "RM 154",
              roi: "2.5×", roi_bad: false },
    charts: {
        leads: { total: "727", slices: [{ key: "email", label: "Email", color: "#71639e", path: SLICE, value: "312", pct: 43 },
                                         { key: "social", label: "Social Media", color: "#d9822b", path: SLICE, value: "273", pct: 38 }] },
        revenue: { total: "RM 276,500", slices: [{ key: "email", label: "Email", color: "#71639e", path: SLICE,
                                                  value: "RM 121,000", pct: 44 }] },
        clicks: { total: "11030", slices: [] },
    },
};

/** Draws the block's template with the panel's methods, recording what each click opens. */
class Host extends Component {
    static template = xml`<div><t t-set="extra" t-value="this.extra"/><t t-call="marketing_intel_tracking.ChannelResults"/></div>`;
    props = useProps({});
    setup() {
        this.extra = { channel_results: RESULTS };
        this.cr = proxy({ measure: "leads", open: {} });
    }
    crToggle(key) { this.cr.open[key] = !this.cr.open[key]; }
    crMeasure(measure) { this.cr.measure = measure; }
    crOpen(measure, row, sub = false) { expect.step(`open:${measure}:${row}${sub ? ":" + sub.join("|") : ""}`); }
    crSliceKeydown(ev, row) { if (ev.key === "Enter") { this.crOpen(this.cr.measure, row); } }
}

test("rows per channel open into their mailings or platforms; numbers open their lists", async () => {
    await mountWithCleanup(Host);
    expect(".o_mi_cr_channel").toHaveCount(2);
    expect(".o_mi_cr_other").toHaveText(/Not from a marketing link/);
    expect(".o_mi_cr_source").toHaveCount(0);
    await contains(".o_mi_cr_channel:first .o_mi_cr_toggle").click();
    expect(".o_mi_cr_source").toHaveCount(1);
    expect(".o_mi_cr_source").toHaveText(/Spring offer/);
    expect(".o_mi_cr_channel:last .o_mi_cr_toggle").toHaveAttribute("disabled");
    await contains(".o_mi_cr_channel:first .o_mi_cr_number:contains(312)").click();
    await contains(".o_mi_cr_source .o_mi_cr_number:contains(201)").click();
    await contains("tfoot .o_mi_cr_number:contains(727)").click();
    expect.verifySteps(["open:leads:email", "open:leads:email:reference|mailing.mailing,5", "open:leads:all"]);
    expect(".o_mi_cr_channel:last td.text-danger").toHaveText("0.9×", { message: "returns less than it spends" });
});

test("the donut chart: every slice, legend line and the total are clickable; the switch redraws it", async () => {
    await mountWithCleanup(Host);
    expect(".o_mi_cr_slice").toHaveCount(2);
    expect(".o_mi_cr_center").toHaveText(/727/);
    await clickSvg(".o_mi_cr_slice");
    await contains(".o_mi_cr_legend_item:last").click();
    await clickSvg(".o_mi_cr_center");
    expect.verifySteps(["open:leads:email", "open:leads:social", "open:leads:all"]);
    await contains(".o_mi_cr_chart button:contains(Revenue)").click();
    expect(".o_mi_cr_slice").toHaveCount(1);
    expect(".o_mi_cr_center").toHaveText(/RM 276,500/);
    await clickSvg(".o_mi_cr_slice");
    expect.verifySteps(["open:revenue:email"]);
    await contains(".o_mi_cr_chart button:contains(Clicks)").click();
    expect(".o_mi_cr_chart .o_mi_empty").toHaveText("Nothing in this period yet.");
});

test("the panel's own template takes the block (its extension applies)", async () => {
    const panel = getTemplate("marketing_intel_plan.Panel");
    const markup = new XMLSerializer().serializeToString(panel);
    expect(markup).toInclude("marketing_intel_tracking.ChannelResults");
    expect(markup).toInclude("!extra.channel_results and extra.columns");
});
