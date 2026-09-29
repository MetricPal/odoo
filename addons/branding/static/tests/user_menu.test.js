import { afterEach, expect, test } from "@odoo/hoot";

import { registry } from "@web/core/registry";
import { removeOdooAccountItem } from "@branding/user_menu/user_menu_items";

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
