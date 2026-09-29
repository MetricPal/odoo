import { registry } from "@web/core/registry";

export function removeOdooAccountItem() {
    const userMenuItems = registry.category("user_menuitems");
    if (userMenuItems.contains("odoo_account")) {
        userMenuItems.remove("odoo_account");
    }
    if (userMenuItems.contains("support")) {
        userMenuItems.remove("support");
    }
    if (userMenuItems.contains("shortcuts")) {
        userMenuItems.remove("shortcuts");
    }
}

removeOdooAccountItem();
