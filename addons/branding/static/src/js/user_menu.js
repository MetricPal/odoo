/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Popover } from "@web/core/popover/popover";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { session } from "@web/session";

const USER_MENU_POPOVER_SELECTOR =
    ".o_popover.o-dropdown--menu.dropdown-menu:has([data-menu='logout'])";

export function offsetUserMenuPopover(popover) {
    if (!popover?.matches(USER_MENU_POPOVER_SELECTOR)) {
        return;
    }
    if (popover.dataset.brandingAdjustedLeft === popover.style.left) {
        return;
    }

    const left = Number.parseFloat(popover.style.left);
    if (!Number.isFinite(left)) {
        return;
    }

    const adjustedLeft = `${left - 4}px`;
    popover.style.left = adjustedLeft;
    popover.dataset.brandingAdjustedLeft = adjustedLeft;
}

patch(Popover.prototype, {
    onPositioned() {
        super.onPositioned(...arguments);
        offsetUserMenuPopover(this.ref());
    },
});

// Odoo 20's UserMenu already owns the real menu actions.
// Add the email needed by the custom profile header.
patch(UserMenu.prototype, {
    setup() {
        super.setup(...arguments);
        this.userEmail = session.user_email || user.login || "";
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
