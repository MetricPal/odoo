import { afterEach, expect, test } from "@odoo/hoot";

import { registry } from "@web/core/registry";
import {
    buildMovedAppMenuItem,
    isMovedUserMenuApp,
    offsetUserMenuPopover,
    removeOdooAccountItem,
} from "@branding/js/user_menu";

const userMenuItems = registry.category("user_menuitems");

afterEach(() => {
    if (userMenuItems.contains("odoo_account")) {
        userMenuItems.remove("odoo_account");
    }
});

test("My Odoo.com Account is removed from the user menu", () => {
    userMenuItems.add("odoo_account", () => ({
        type: "item",
        id: "account",
        description: "My Odoo.com Account",
    }));

    removeOdooAccountItem();

    expect(userMenuItems.contains("odoo_account")).toBe(false);
});

test("user menu popover is shifted four pixels left after positioning", () => {
    const popover = document.createElement("div");
    popover.className = "o_popover o-dropdown--menu dropdown-menu";
    popover.style.left = "844px";
    popover.innerHTML = '<div data-menu="logout"></div>';

    offsetUserMenuPopover(popover);
    expect(popover.style.left).toBe("840px");

    // Repeated callbacks without a new raw position must not accumulate offsets.
    offsetUserMenuPopover(popover);
    expect(popover.style.left).toBe("840px");
});

test("Apps and Settings roots are identified for removal from the app launcher", () => {
    expect(isMovedUserMenuApp({ xmlid: "base.menu_management" })).toBe(true);
    expect(isMovedUserMenuApp({ xmlid: "base.menu_administration" })).toBe(true);
    expect(isMovedUserMenuApp({ xmlid: "mail.menu_root_discuss" })).toBe(false);
});

test("moved app user-menu item keeps native app navigation", async () => {
    const apps = [{
        xmlid: "base.menu_management",
        actionPath: "apps",
    }];
    let selectedApp;
    const menuService = {
        getApps: () => apps,
        selectMenu: (app) => {
            selectedApp = app;
        },
    };
    const item = buildMovedAppMenuItem(menuService, {
        id: "apps",
        description: "Apps",
        xmlid: "base.menu_management",
        sequence: 67,
    });

    expect(item.hide).toBe(false);
    expect(item.href).toBe("/odoo/apps");
    expect(item.sequence).toBe(67);
    await item.callback();
    expect(selectedApp).toBe(apps[0]);
});

test("moved app user-menu item is hidden without menu access", () => {
    const item = buildMovedAppMenuItem(
        { getApps: () => [], selectMenu: () => {} },
        {
            id: "settings",
            description: "Settings",
            xmlid: "base.menu_administration",
            sequence: 68,
        }
    );

    expect(item.hide).toBe(true);
});
