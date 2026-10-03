import { NavBar } from "@web/webclient/navbar/navbar";

import { Component, useProps } from "@odoo/owl";

/**
 * Presentational shell for the future cross-application search experience.
 *
 * Odoo's command service already owns the global Ctrl+K command palette. The
 * shell deliberately has no click handler yet so search providers and result
 * behavior can be designed separately without changing the navbar layout.
 */
export class WorkDashboardGlobalSearch extends Component {
    static template = "ai_home.GlobalSearch";
    props = useProps({});
}

NavBar.components = {
    ...NavBar.components,
    WorkDashboardGlobalSearch,
};
