/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { UserMenu } from "@web/webclient/user_menu/user_menu";

// Odoo 20's UserMenu already owns the real menu actions.
// We only add the email needed by the custom profile header.
patch(UserMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.userEmail = user.email || "";
    },
});

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
