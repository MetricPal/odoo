import { registry } from "@web/core/registry";
import { Layout } from "@web/search/layout";
import { Component, useProps } from "@odoo/owl";

/**
 * A report page of Insights › Reports. Each report is built from its own approved mock; until then the page shows
 * its name in Odoo's control panel and says it is not built yet.
 */
export class ReportPage extends Component {
    static template = "marketing_intel_reports.ReportPage";
    static components = { Layout };
    props = useProps();
}

registry.category("actions").add("marketing_intel_reports.page", ReportPage);
