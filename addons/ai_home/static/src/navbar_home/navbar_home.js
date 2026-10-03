import { browser } from "@web/core/browser/browser";
import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

import { WORK_DASHBOARD_ROUTE } from "./home_route";

export const WORK_DASHBOARD_MENU_XMLID = "ai_home.menu_ai_home_root";

patch(NavBar.prototype, {
    get workDashboardMenu() {
        return this.menuService
            .getApps()
            .find((app) => app.xmlid === WORK_DASHBOARD_MENU_XMLID);
    },

    get isWorkDashboardCurrentApp() {
        return this.currentApp?.xmlid === WORK_DASHBOARD_MENU_XMLID;
    },

    openWorkDashboard() {
        if (
            this.isWorkDashboardCurrentApp &&
            browser.location.pathname === WORK_DASHBOARD_ROUTE
        ) {
            return;
        }
        if (this.workDashboardMenu) {
            this.menuService.selectMenu(this.workDashboardMenu);
        }
    },
});
