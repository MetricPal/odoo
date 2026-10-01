/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Popover } from "@web/core/popover/popover";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { NavBar } from "@web/webclient/navbar/navbar";
import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { session } from "@web/session";

const USER_MENU_POPOVER_SELECTOR =
    ".o_popover.o-dropdown--menu.dropdown-menu:has([data-menu='logout'])";

export const MOVED_USER_MENU_APPS = {
    apps: "base.menu_management",
    settings: "base.menu_administration",
};

export function isMovedUserMenuApp(app) {
    return Object.values(MOVED_USER_MENU_APPS).includes(app.xmlid);
}

export function buildMovedAppMenuItem(menuService, { id, description, xmlid, sequence }) {
    const app = menuService.getApps().find((candidate) => candidate.xmlid === xmlid);
    return {
        type: "item",
        id,
        description,
        href: app ? `/odoo/${app.actionPath || `action-${app.actionID}`}` : undefined,
        callback: () => app && menuService.selectMenu(app),
        hide: !app,
        sequence,
    };
}

function movedAppsSeparator() {
    const menuService = useService("menu");
    return {
        type: "separator",
        hide: !menuService.getApps().some(isMovedUserMenuApp),
        sequence: 66,
    };
}

function appsItem() {
    return buildMovedAppMenuItem(useService("menu"), {
        id: "apps",
        description: _t("Apps"),
        xmlid: MOVED_USER_MENU_APPS.apps,
        sequence: 67,
    });
}

function settingsItem() {
    return buildMovedAppMenuItem(useService("menu"), {
        id: "settings",
        description: _t("Settings"),
        xmlid: MOVED_USER_MENU_APPS.settings,
        sequence: 68,
    });
}

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

patch(NavBar.prototype, {
    getBrandingApps() {
        return this.menuService.getApps().filter((app) => !isMovedUserMenuApp(app));
    },
});

registry
    .category("user_menuitems")
    .add("branding_apps_separator", movedAppsSeparator)
    .add("branding_apps", appsItem)
    .add("branding_settings", settingsItem);

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
