import { afterEach, expect, test } from "@odoo/hoot";

import { registry } from "@web/core/registry";
import {
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
