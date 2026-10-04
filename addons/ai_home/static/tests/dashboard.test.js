import { beforeEach, expect, test } from "@odoo/hoot";
import { queryOne, resize } from "@odoo/hoot-dom";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import {
    contains,
    mockService,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

import {
    AUTOMATION_LIMIT,
    FAVORITE_LIMIT,
    RECENT_VISIBLE_LIMIT,
    WorkDashboard,
    buildFavoriteSlots,
    compactFavoriteIds,
    insertFavoriteAtSlot,
    moveFavoriteToSlot,
    splitDashboardItems,
} from "@ai_home/dashboard/dashboard";

const dashboardItems = [
    ...Array.from({ length: 5 }, (_, index) => ({
        id: index + 1,
        name: `Attention ${index + 1}`,
        section: "attention",
        subtitle: "Review requested",
        occurredLabel: "Now",
        iconText: "AT",
        tone: "warning",
    })),
    ...Array.from({ length: 6 }, (_, index) => ({
        id: index + 11,
        name: `Automation ${index + 1}`,
        section: "automation",
        subtitle: "Completed",
        occurredLabel: "Today",
        iconText: "AU",
        tone: "success",
    })),
    ...Array.from({ length: 8 }, (_, index) => ({
        id: index + 21,
        name: `Recent ${index + 1}`,
        section: "recent",
        subtitle: "Updated",
        occurredLabel: "Today",
        iconText: "RE",
        tone: "primary",
    })),
];

const apps = [
    { id: 90, name: "Apps", xmlid: "base.menu_management", actionID: 90 },
    { id: 91, name: "Settings", xmlid: "base.menu_administration", actionID: 91 },
    { id: 1, name: "Home", xmlid: "ai_home.menu_ai_home_root", actionID: 1 },
    { id: 2, name: "Sales", xmlid: "sale.menu_sale_root", actionID: 2 },
    { id: 3, name: "Inventory", xmlid: "stock.menu_stock_root", actionID: 3 },
    { id: 4, name: "Employees", xmlid: "hr.menu_hr_root", actionID: 4 },
    ...Array.from({ length: 10 }, (_, index) => ({
        id: index + 5,
        name: `App ${index + 1}`,
        xmlid: `test.menu_app_${index + 1}`,
        actionID: index + 5,
    })),
];

beforeEach(() => {
    patchWithCleanup(user, { userId: 42 });
    browser.localStorage.removeItem("ai_home.favorite_apps.42");
    mockService("menu", {
        getApps: () => apps,
        selectMenu: (app) => expect.step(`open ${app.name}`),
    });
    mockService("notification", { add: () => {} });
    mockService("orm", {
        async call(model, method, args) {
            expect(model).toBe("ai.home.item");
            if (method === "get_dashboard_items") {
                return dashboardItems;
            }
            if (method === "mark_recent_seen") {
                expect.step(`seen ${args[0]}`);
                return true;
            }
        },
    });
    return () => browser.localStorage.removeItem("ai_home.favorite_apps.42");
});

test("dashboard helpers preserve section and capacity rules", () => {
    const sections = splitDashboardItems(dashboardItems);

    expect(sections.attention).toHaveLength(5);
    expect(sections.automations).toHaveLength(6);
    expect(sections.recent).toHaveLength(8);
    expect(buildFavoriteSlots(apps.slice(0, 3))).toHaveLength(FAVORITE_LIMIT);
    expect(compactFavoriteIds([2, null, 3]).slice(0, 3)).toEqual([2, 3, null]);
    expect(moveFavoriteToSlot([2, 3, 4], 2, 1).slice(0, 3)).toEqual([3, 2, 4]);
    expect(insertFavoriteAtSlot([2, 3, null, 4], 5, 2).slice(0, 4)).toEqual([
        2, 3, 5, 4,
    ]);
    expect(insertFavoriteAtSlot([2, 3, null, 4], 5, 1).slice(0, 4)).toEqual([
        2, 5, 3, 4,
    ]);
});

test("an intentionally empty favorite list remains empty", async () => {
    browser.localStorage.setItem("ai_home.favorite_apps.42", "[]");

    await mountWithCleanup(WorkDashboard);

    expect(".o_ai_home_favorite_slot").toHaveCount(FAVORITE_LIMIT);
    expect(".o_ai_home_favorite_slot.o_is_empty").toHaveCount(FAVORITE_LIMIT);
});

test("dashboard binds its sortable reference and reacts to state changes", async () => {
    const dashboard = await mountWithCleanup(WorkDashboard);

    expect(dashboard.favoritesRootRef()).toBe(queryOne(".o_ai_home_favorites"));
    await contains(".o_ai_home_favorites_view_all").click();
    expect(dashboard.state.showAllApps).toBe(true);
    expect(".o_ai_home_all_app").toHaveCount(3);
});

test("renders responsive section capacities and expands requested content", async () => {
    await resize({ width: 1366 });
    await mountWithCleanup(WorkDashboard);

    expect(".o_ai_home_attention_card").toHaveCount(3);
    expect(
        ".o_ai_home_attention > .o_ai_home_section_heading .o_ai_home_show_more"
    ).toHaveText("Show more");
    expect(".o_ai_home_show_more").toHaveAttribute("aria-expanded", "false");
    expect(".o_ai_home_show_more .o_ai_home_section_caret").toHaveCount(1);
    const collapsedCardHeight = queryOne(
        ".o_ai_home_attention_card"
    ).getBoundingClientRect().height;
    expect(".o_ai_home_favorite_slot").toHaveCount(FAVORITE_LIMIT);
    expect(".o_ai_home_automation_card").toHaveCount(AUTOMATION_LIMIT);
    expect(".o_ai_home_recent_card").toHaveCount(RECENT_VISIBLE_LIMIT);

    await contains(".o_ai_home_show_more").click();
    expect(".o_ai_home_attention_card").toHaveCount(5);
    expect(".o_ai_home_show_more").toHaveText("Show less");
    expect(".o_ai_home_show_more").toHaveAttribute("aria-expanded", "true");
    expect(".o_ai_home_show_more .o_ai_home_section_caret").toHaveCount(1);
    expect(queryOne(".o_ai_home_attention_card").getBoundingClientRect().height).toBe(
        collapsedCardHeight
    );

    await contains(".o_ai_home_favorites_view_all").click();
    expect(".o_ai_home_favorites_view_all").toHaveAttribute("aria-expanded", "true");
    expect(".o_ai_home_all_app").toHaveCount(3);
    expect(".o_ai_home_all_app .o_ai_home_app_icon").toHaveCount(3);
    expect(".o_ai_home_all_app .o_ai_home_app_name").toHaveCount(3);
    expect(".o_ai_home_favorite_item .o_ai_home_favorite_toggle").toHaveCount(10);

    await contains(".o_ai_home_all_app .o_ai_home_favorite_toggle").click();
    expect(".o_ai_home_all_app").toHaveCount(2);
    expect(".o_ai_home_favorite_item .o_ai_home_favorite_toggle").toHaveCount(11);

    await contains(".o_ai_home_recent_view_all").click();
    expect(".o_ai_home_recent_view_all").toHaveAttribute("aria-expanded", "true");
    expect(".o_ai_home_recent_card").toHaveCount(8);
});

test("favorite apps open and recent cards become seen", async () => {
    await mountWithCleanup(WorkDashboard);

    await contains(".o_ai_home_favorite_slot", { text: "Sales" }).click();
    await contains(".o_ai_home_recent_card", { text: "Recent 1" }).click();

    expect.verifySteps(["open Sales", "seen 21"]);
    expect(".o_ai_home_recent_card").toHaveCount(RECENT_VISIBLE_LIMIT);
    await contains(".o_ai_home_recent_card", { text: "Recent 1", count: 0 });
});

test("favorite items can be reordered by drag and drop", async () => {
    browser.localStorage.setItem("ai_home.favorite_apps.42", JSON.stringify([2, 3, 4]));
    await mountWithCleanup(WorkDashboard);

    await contains('[data-favorite-origin="favorite"][data-app-id="2"]').dragAndDrop(
        '[data-favorite-origin="favorite"][data-app-id="3"]'
    );

    expect(JSON.parse(browser.localStorage.getItem("ai_home.favorite_apps.42")).slice(0, 3)).toEqual([
        3, 2, 4,
    ]);
});

test("hovering a remaining app reserves and restores one empty slot", async () => {
    browser.localStorage.setItem("ai_home.favorite_apps.42", JSON.stringify([2, 3]));
    await mountWithCleanup(WorkDashboard);
    await contains(".o_ai_home_favorites_view_all").click();

    const { cancel, moveTo } = await contains(
        '[data-favorite-origin="available"][data-app-id="5"]'
    ).drag();
    await moveTo('.o_ai_home_favorite_item[data-slot-index="1"]');
    expect(".o_ai_home_favorite_item.o_is_reserved_empty").toHaveCount(1);

    await cancel();
    expect(".o_ai_home_favorite_item.o_is_reserved_empty").toHaveCount(0);
});

test("a remaining app can be dropped at an exact favorite position", async () => {
    browser.localStorage.setItem(
        "ai_home.favorite_apps.42",
        JSON.stringify([2, 3, null, 4])
    );
    await mountWithCleanup(WorkDashboard);
    expect('.o_ai_home_favorite_item[data-slot-index="2"][data-app-id="4"]').toHaveCount(1);
    expect('.o_ai_home_favorite_item[data-slot-index="3"].o_is_empty').toHaveCount(1);
    await contains(".o_ai_home_favorites_view_all").click();

    await contains('[data-favorite-origin="available"][data-app-id="5"]').dragAndDrop(
        '.o_ai_home_favorite_item[data-slot-index="1"]'
    );

    expect(JSON.parse(browser.localStorage.getItem("ai_home.favorite_apps.42")).slice(0, 4)).toEqual([
        2, 5, 3, 4,
    ]);
});


test("favorite stars are visible only after View all and administrative apps are excluded", async () => {
    browser.localStorage.setItem("ai_home.favorite_apps.42", JSON.stringify([90, 2, 91]));
    await mountWithCleanup(WorkDashboard);

    expect('.o_ai_home_favorite_item [data-icon="star"].oi-filled').toHaveCount(0);
    expect(".o_ai_home_favorite_item .o_ai_home_app_name").toHaveText("Sales");
    await contains(".o_ai_home_favorites_view_all").click();
    expect('.o_ai_home_favorite_item [data-icon="star"].oi-filled').toHaveCount(1);
    expect('[data-app-id="90"]').toHaveCount(0);
    expect('[data-app-id="91"]').toHaveCount(0);
});
