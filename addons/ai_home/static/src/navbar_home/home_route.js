import { browser } from "@web/core/browser/browser";
import { router } from "@web/core/browser/router";
import { patch } from "@web/core/utils/patch";

export const WORK_DASHBOARD_ACTION_XMLID = "ai_home.action_ai_home";
export const WORK_DASHBOARD_ROUTE = "/odoo/home";

const WORK_DASHBOARD_XMLID_ROUTE = `/odoo/action-${WORK_DASHBOARD_ACTION_XMLID}`;

function replaceHomeActionWithDashboard(action) {
    return action === "home" ? WORK_DASHBOARD_ACTION_XMLID : action;
}

/**
 * `home` is a core client-action tag, so the action service resolves it before
 * database action paths. Translate the Home URL to its XMLID
 * and leave Odoo's built-in `home` client action untouched everywhere else.
 */
patch(router, {
    stateToUrl(state) {
        const url = super.stateToUrl(state);
        if (
            url === WORK_DASHBOARD_XMLID_ROUTE ||
            url.startsWith(`${WORK_DASHBOARD_XMLID_ROUTE}?`)
        ) {
            return url.replace(WORK_DASHBOARD_XMLID_ROUTE, WORK_DASHBOARD_ROUTE);
        }
        return url;
    },

    urlToState(urlObj) {
        const pathname = urlObj.pathname;
        const state = super.urlToState(urlObj);
        if (
            ["/odoo", "/odoo/"].includes(pathname) &&
            !state.action && !state.model && !state.menu_id &&
            !state.actionStack?.length
        ) {
            return {
                ...state,
                action: WORK_DASHBOARD_ACTION_XMLID,
                actionStack: [{ action: WORK_DASHBOARD_ACTION_XMLID }],
            };
        }
        if (pathname !== WORK_DASHBOARD_ROUTE) {
            return state;
        }
        return {
            ...state,
            action: replaceHomeActionWithDashboard(state.action),
            actionStack: state.actionStack?.map((actionState) => ({
                ...actionState,
                action: replaceHomeActionWithDashboard(actionState.action),
            })),
        };
    },
});

// The router initializes before addon patches are evaluated. Refresh its
// in-memory state synchronously when the web client was opened through this
// alias, following the same extension pattern used by Odoo's project sharing.
if (["/odoo", "/odoo/", WORK_DASHBOARD_ROUTE].includes(browser.location.pathname)) {
    router.replaceState(router.urlToState(new URL(browser.location.href)), { sync: true });
}
