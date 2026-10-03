import { expect, test } from "@odoo/hoot";
import { defineMenus, mountWithCleanup } from "@web/../tests/web_test_helpers";
import { NavBar } from "@web/webclient/navbar/navbar";

import { WorkDashboardGlobalSearch } from "@ai_home/global_search/global_search";

test.tags("desktop");

test("global search mounts with the Owl 3 props API", async () => {
    await mountWithCleanup(WorkDashboardGlobalSearch);
    expect(".o_ai_home_global_search").toHaveCount(1);
});

test("global search shell is available in the backend navbar", async () => {
    defineMenus([
        {
            id: 1,
            name: "Home",
            xmlid: "ai_home.menu_ai_home_root",
            actionID: 1,
        },
    ]);

    await mountWithCleanup(NavBar);

    expect(".o_main_navbar .o_ai_home_global_search").toHaveCount(1);
    expect(".o_ai_home_global_search").toHaveAttribute("role", "search");
    expect(".o_ai_home_global_search_shell").toHaveAttribute(
        "aria-disabled",
        "true"
    );
    expect(".o_ai_home_global_search_label").toHaveText(
        "Search apps, records, and actions"
    );
    expect(".o_ai_home_global_search_shortcut").toHaveText("CtrlK");
    expect(NavBar.components.WorkDashboardGlobalSearch).toBe(WorkDashboardGlobalSearch);
});
