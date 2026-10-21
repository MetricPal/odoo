import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { router } from "@web/core/browser/router";
import { registry } from "@web/core/registry";
import { NavBar } from "@web/webclient/navbar/navbar";

import {
    WORK_DASHBOARD_ACTION_XMLID,
    WORK_DASHBOARD_ROUTE,
} from "@ai_home/navbar_home/home_route";
import { WORK_DASHBOARD_MENU_XMLID } from "@ai_home/navbar_home/navbar_home";

// The navbar systray talks to Discuss; its models must exist in the mock server.
defineMailModels();

const homeApp = {
    id: 1,
    name: "Home",
    xmlid: WORK_DASHBOARD_MENU_XMLID,
    actionID: 10,
    actionPath: "home",
};
const salesApp = {
    id: 2,
    name: "Sales",
    xmlid: "sale.menu_sale_root",
    actionID: 20,
};

function mockMenuService(currentApp) {
    mockService("menu", {
        getApps: () => [homeApp, salesApp],
        getCurrentApp: () => currentApp,
        getMenuAsTree: () => ({ childrenTree: [] }),
        selectMenu: (menu) => expect.step(`open ${menu.xmlid}`),
    });
}

test.tags("desktop");

test("the logo's /odoo entry URL opens Home and canonicalizes the address", () => {
    for (const path of ["/odoo", "/odoo/"]) {
        const state = router.urlToState(new URL(`http://localhost${path}?debug=1`));
        expect(state.action).toBe(WORK_DASHBOARD_ACTION_XMLID);
        expect(state.actionStack).toEqual([{ action: WORK_DASHBOARD_ACTION_XMLID }]);
        expect(router.stateToUrl(state)).toBe(`${WORK_DASHBOARD_ROUTE}?debug=1`);
    }
});

test("explicit application routes retain their action", () => {
    const state = router.urlToState(new URL("http://localhost/odoo/action-sale.action_orders"));
    expect(state.action).toBe("sale.action_orders");
    expect(router.stateToUrl(state)).toBe("/odoo/action-sale.action_orders");
});

test("/odoo/home resolves to Home without replacing Odoo's home client action", () => {
    const state = router.urlToState(new URL("http://localhost/odoo/home"));

    expect(state.action).toBe(WORK_DASHBOARD_ACTION_XMLID);
    expect(state.actionStack).toEqual([{ action: WORK_DASHBOARD_ACTION_XMLID }]);
    expect(router.stateToUrl(state)).toBe(WORK_DASHBOARD_ROUTE);
    expect(registry.category("actions").contains("home")).toBe(true);
});

test.tags("desktop");

test("desktop app launcher remains available", async () => {
    mockMenuService(salesApp);
    await mountWithCleanup(NavBar);
    expect(".o_navbar_apps_menu button").toHaveCount(1);
    expect(".o_ai_home_home_menu").toHaveCount(0);
    expect(".o_menu_brand").toHaveText("Sales");
});

test.tags("desktop");

test("Home app-brand text is not rendered in the navbar", async () => {
    mockMenuService(homeApp);

    await mountWithCleanup(NavBar);

    expect(".o_menu_brand").toHaveCount(0);
    expect(".o_ai_home_global_search").toHaveCount(0);
});

test.tags("mobile");

test("native mobile app launcher remains available", async () => {
    mockMenuService(salesApp);
    await mountWithCleanup(NavBar);
    expect(".o_menu_toggle").toHaveCount(1);
    expect(".o_ai_home_home_menu").toHaveCount(0);
});
