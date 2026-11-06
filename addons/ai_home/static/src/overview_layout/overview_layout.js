import { useEnv, useSubEnv } from "@odoo/owl";
import { Breadcrumbs } from "@web/search/breadcrumbs/breadcrumbs";
import { ControlPanel } from "@web/search/control_panel/control_panel";

/** Breadcrumbs that write out every step (Home / System overview / All insights) instead of folding into "…". */
export class FullBreadcrumbs extends Breadcrumbs {
    static template = "ai_home.FullBreadcrumbs";
}

export class OverviewControlPanel extends ControlPanel {
    static components = { ...ControlPanel.components, Breadcrumbs: FullBreadcrumbs };
}

/**
 * The System overview, All insights and app reports use Odoo's Layout with this control panel. The config keeps
 * the action's own (live) values through its prototype and only adds the control panel.
 */
export function useOverviewControlPanel() {
    const env = useEnv();
    useSubEnv({ config: Object.create(env.config, { ControlPanel: { value: OverviewControlPanel } }) });
}
