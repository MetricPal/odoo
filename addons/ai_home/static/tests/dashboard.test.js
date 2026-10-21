import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { beforeEach, expect, test } from "@odoo/hoot";
import { animationFrame, resize } from "@odoo/hoot-dom";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import {
    contains,
    mockService,
    mountWithCleanup,
    patchWithCleanup,
} from "@web/../tests/web_test_helpers";

import {
    ATTACHMENT_LIMIT,
    MY_WORK_MIN_FIT,
    WorkDashboard,
    filterAutomations,
    groupWorkByDay,
    myWorkVisibleCount,
    splitDashboardItems,
} from "@ai_home/dashboard/dashboard";

defineMailModels();

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

function makeMyWork(extra = 0) {
    return [
        {
            key: "work-res.partner-1",
            name: "Azure Interior",
            subtitle: "Contact · You commented",
            occurred: luxon.DateTime.utc().toFormat("yyyy-MM-dd HH:mm:ss"),
            iconText: "CO",
            action: { res_model: "res.partner", res_id: 1 },
        },
        {
            key: "work-sale.order-9",
            name: "S00009",
            subtitle: "Sales Order · You updated",
            occurred: luxon.DateTime.utc().minus({ days: 30 }).toFormat("yyyy-MM-dd HH:mm:ss"),
            iconText: "SA",
            action: { res_model: "sale.order", res_id: 9 },
        },
        ...Array.from({ length: extra }, (_, index) => ({
            key: `work-crm.lead-${index}`,
            name: `Lead ${index}`,
            subtitle: "Lead · You updated",
            occurred: luxon.DateTime.utc().minus({ days: 40 + index }).toFormat("yyyy-MM-dd HH:mm:ss"),
            iconText: "LE",
            action: { res_model: "crm.lead", res_id: index + 100 },
        })),
    ];
}
let extraWork = 0;
let homeAgents = [];
const workflowRuns = [
    { key: "run-5", name: "Invoice reminder", subtitle: "INV/2026/0007", status: "failed",
      statusLabel: "Failed", occurred: "2020-01-01 10:00:00", action: { res_model: "workflow.run", res_id: 5 } },
    { key: "run-4", name: "New lead first call", subtitle: "Azure Interior", status: "done",
      statusLabel: "Done", occurred: "2020-01-01 09:00:00", action: { res_model: "workflow.run", res_id: 4 } },
];
const liveAutomations = [
    { key: "workflow-1", name: "Overdue follow-up", subtitle: "Schedule", status: "paused", tone: "neutral",
      occurred: "2020-01-01 10:00:00", action: { res_model: "workflow.definition", res_id: 1 } },
    { key: "workflow-2", name: "Invoice reminder", subtitle: "2 failed runs", status: "failed", tone: "danger",
      occurred: "2020-01-01 10:00:00", action: { res_model: "workflow.definition", res_id: 2 } },
];
function homeData() {
    return {
        items: dashboardItems,
        attention: [],
        automations: liveAutomations,
        runs: workflowRuns,
        myWork: makeMyWork(extraWork),
        agents: homeAgents,
        canManageAgents: false,
    };
}

const apps = [
    { id: 1, name: "Home", xmlid: "ai_home.menu_ai_home_root", actionID: 1 },
    { id: 2, name: "Sales", xmlid: "sale.menu_sale_root", actionID: 2 },
];

beforeEach(() => {
    extraWork = 0;
    homeAgents = [];
    patchWithCleanup(user, { userId: 42 });
    mockService("menu", {
        getApps: () => apps,
        selectMenu: (app) => expect.step(`open ${app.name}`),
    });
    mockService("notification", { add: () => {} });
    mockService("action", { doAction: () => {} });
    mockService("orm", {
        async call(model, method, args) {
            expect(model).toBe("ai.home.item");
            if (method === "get_home_data") {
                return homeData();
            }
            if (method === "mark_recent_seen") {
                expect.step(`seen ${args[0]}`);
                return true;
            }
        },
    });
});

test("dashboard helpers preserve section rules", () => {
    const sections = splitDashboardItems(dashboardItems);
    expect(sections.attention).toHaveLength(5);
    expect(sections.automations).toHaveLength(6);
    expect(sections.recent).toHaveLength(8);
});

test("My Work shows what fits, then twice that when there is more", () => {
    expect(myWorkVisibleCount(5, 10)).toBe(5);
    expect(myWorkVisibleCount(10, 10)).toBe(10);
    expect(myWorkVisibleCount(11, 10)).toBe(11);
    expect(myWorkVisibleCount(60, 10)).toBe(20);
    expect(myWorkVisibleCount(60, 0)).toBe(MY_WORK_MIN_FIT * 2);
});

test("Home has no favorites and the composer stays outside the scrolling center", async () => {
    await resize({ width: 1366 });
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_favorites").toHaveCount(0);
    expect(".o_ai_home_mywork_more").toHaveCount(0);
    expect(".o_ai_home_container > .o_ai_home_composer").toHaveCount(1);
    expect(".o_ai_home_center .o_ai_home_composer").toHaveCount(0);
});

test("renders section capacities and expands requested content", async () => {
    await resize({ width: 1366 });
    await mountWithCleanup(WorkDashboard);

    expect(".o_ai_home_attention_card").toHaveCount(3);
    expect(".o_ai_home_show_more").toHaveText("Show more");
    expect(".o_ai_home_show_more").toHaveAttribute("aria-expanded", "false");
    expect(".o_ai_home_left .o_ai_home_mywork").toHaveCount(1);
    expect(".o_ai_home_right .o_ai_home_automations").toHaveCount(1);
    expect(".o_ai_home_right .o_ai_home_runs").toHaveCount(1);
    expect(".o_ai_home_right .o_ai_home_recent").toHaveCount(1);
    // Every row is rendered; the section scrolls instead of a View all button.
    expect(".o_ai_home_automation_row").toHaveCount(8);
    expect(".o_ai_home_recent_row").toHaveCount(8);
    expect(".o_ai_home_automations_view_all, .o_ai_home_recent_view_all").toHaveCount(0);
    expect(".o_ai_home_automations .o_ai_home_count").toHaveText("8");
    expect(".o_ai_home_right .o_ai_home_panel.o_ai_home_scroll").toHaveCount(3);
    expect(".o_ai_home_mywork > .o_ai_home_section_heading + .o_ai_home_mywork_list").toHaveCount(1);

    await contains(".o_ai_home_show_more").click();
    expect(".o_ai_home_attention_card").toHaveCount(5);
    expect(".o_ai_home_show_more").toHaveText("Show less");
});

test("recent rows become seen when opened", async () => {
    await mountWithCleanup(WorkDashboard);
    await contains('.o_ai_home_recent_row[aria-label="Open Recent 1"]').click();
    expect.verifySteps(["seen 21"]);
    expect('.o_ai_home_recent_row[aria-label="Open Recent 1"]').toHaveCount(0);
});

test("workflow runs show their state and open the run", async () => {
    let opened;
    mockService("action", { doAction: (action) => { opened = action; } });
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_run_row").toHaveCount(2);
    expect(".o_ai_home_run_row:first .o_ai_home_pill").toHaveText("Failed");
    expect(".o_ai_home_run_row:first .o_ai_home_pill").toHaveClass("o_run_failed");
    await contains('.o_ai_home_run_row[aria-label="Open Invoice reminder run"]').click();
    expect(opened.res_model).toBe("workflow.run");
    expect(opened.res_id).toBe(5);
});

test("My Work renders twice the rows that fit when the history is longer", async () => {
    extraWork = 40;
    patchWithCleanup(WorkDashboard.prototype, {
        measureMyWork() {
            this.state.myWorkFit = 6;
        },
    });
    await mountWithCleanup(WorkDashboard);
    await animationFrame();
    expect(".o_ai_home_mywork_item").toHaveCount(12);
});

test("the agent picker lists active agents and remembers the choice", async () => {
    homeAgents = [
        { id: 7, name: "Sales Assistant", description: "Pipeline and quotes" },
        { id: 8, name: "HR Helper", description: "" },
    ];
    browser.localStorage.removeItem("ai_home.agent");
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_agent_name").toHaveText("Select agent");
    await contains(".o_ai_home_agent_toggle").click();
    expect(".o_ai_home_agent_option").toHaveCount(2);
    expect(".o_ai_home_agent_manage").toHaveCount(0);
    await contains('.o_ai_home_agent_option:contains("HR Helper")').click();
    expect(".o_ai_home_agent_name").toHaveText("HR Helper");
    expect(browser.localStorage.getItem("ai_home.agent")).toBe("8");
    browser.localStorage.removeItem("ai_home.agent");
});

test("one agent is selected automatically; none shows a clear state", async () => {
    homeAgents = [{ id: 7, name: "Sales Assistant", description: "" }];
    const dashboard = await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_agent_name").toHaveText("Sales Assistant");
    dashboard.state.agents = [];
    dashboard.state.agentId = "";
    await animationFrame();
    expect(".o_ai_home_agent_name").toHaveText("No active agent");
});

test("files can be attached, removed and travel with the question", async () => {
    const created = [];
    const unlinked = [];
    mockService("orm", {
        async call(model, method, args) {
            if (model === "ai.home.item") {
                return method === "get_home_data" ? homeData() : true;
            }
            return { type: "ir.actions.act_window", res_model: "ai.agent.conversation", res_id: 3 };
        },
        async create(model, records) {
            created.push([model, records[0]]);
            return [model === "ir.attachment" ? 40 + created.length : 11];
        },
        async unlink(model, ids) {
            unlinked.push([model, ids]);
            return true;
        },
    });
    homeAgents = [{ id: 7, name: "Sales Assistant", description: "" }];
    const dashboard = await mountWithCleanup(WorkDashboard);
    await dashboard.addFiles([
        new File(["# Brief"], "brief.md", { type: "text/markdown" }),
        new File(["x"], "photo.png", { type: "image/png" }),
        new File(["a,b"], "numbers.csv", { type: "text/csv" }),
    ]);
    await animationFrame();
    expect(".o_ai_home_attachment").toHaveCount(2);
    expect(created.map(([model, values]) => [model, values.name])).toEqual([
        ["ir.attachment", "brief.md"],
        ["ir.attachment", "numbers.csv"],
    ]);
    await contains('.o_ai_home_attachment_remove[aria-label="Remove numbers.csv"]').click();
    expect(unlinked).toEqual([["ir.attachment", [42]]]);
    expect(".o_ai_home_attachment").toHaveCount(1);
    dashboard.state.mode = "auto";
    dashboard.state.prompt = "Summarize the brief";
    await dashboard.sendPrompt();
    const ask = created.find(([model]) => model === "ai.agent.ask")[1];
    expect(ask.attachment_ids).toEqual([[6, 0, [41]]]);
    expect(dashboard.state.attachments).toHaveLength(0);
    expect(ATTACHMENT_LIMIT).toBe(5);
});

test("Ask me prepares a draft and opens review without sending", async () => {
    let request;
    mockService("action", { doAction: (action) => { request = action; } });
    const dashboard = await mountWithCleanup(WorkDashboard);
    await contains(".o_ai_home_add").click();
    expect(".o_ai_home_attach").toHaveCount(1);
    await contains(".o_ai_home_prepare").click();
    expect("#ai_home_prompt").toHaveValue("Prepare an approval request for ");
    dashboard.state.agents = [{ id: 7, name: "Sales Assistant" }];
    dashboard.state.agentId = "7";
    dashboard.state.attachments = [{ id: 41, name: "brief.md" }];
    dashboard.reviewRequest();
    expect(request.res_model).toBe("ai.agent.ask");
    expect(request.target).toBe("new");
    expect(request.context.default_agent_id).toBe(7);
    expect(request.context.default_prompt).toBe("Prepare an approval request for");
    expect(request.context.default_attachment_ids).toEqual([41]);
});

test("My Work groups history by day and opens the record", async () => {
    const groups = groupWorkByDay(makeMyWork());
    expect(groups.map((group) => group.key)).toEqual(["today", "earlier"]);
    let opened;
    mockService("action", { doAction: (action) => { opened = action; } });
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_mywork_day").toHaveCount(2);
    expect(".o_ai_home_mywork_item").toHaveCount(2);
    await contains('.o_ai_home_mywork_item[aria-label="Open Azure Interior"]').click();
    expect(opened.res_model).toBe("res.partner");
    expect(opened.res_id).toBe(1);
});

test("Automations can be filtered by status", async () => {
    expect(filterAutomations(liveAutomations, "failed")).toHaveLength(1);
    expect(filterAutomations(liveAutomations, "all")).toHaveLength(2);
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_status_chip").toHaveCount(4); // all, active, paused, needs attention
    await contains('.o_ai_home_status_chip:contains("Needs attention")').click();
    expect(".o_ai_home_automation_row").toHaveCount(1);
    expect(".o_ai_home_automation_row").toHaveAttribute("aria-label", "Open Invoice reminder");
    expect(".o_ai_home_automation_row .o_ai_home_pill").toHaveText("Needs attention");
    await contains('.o_ai_home_status_chip:contains("Paused")').click();
    expect(".o_ai_home_automation_row").toHaveCount(1);
});

test("Auto mode sends the question through the Ask dialog's Send", async () => {
    const calls = [];
    mockService("orm", {
        async call(model, method, args) {
            if (model === "ai.home.item") {
                return method === "get_home_data" ? homeData() : true;
            }
            calls.push([model, method, args]);
            return { type: "ir.actions.act_window", res_model: "ai.agent.conversation", res_id: 3 };
        },
        async create(model, records) {
            calls.push([model, "create", records]);
            return [11];
        },
    });
    let opened;
    mockService("action", { doAction: (action) => { opened = action; } });
    const dashboard = await mountWithCleanup(WorkDashboard);
    dashboard.state.agents = [{ id: 7, name: "Sales Assistant" }];
    dashboard.state.agentId = "7";
    dashboard.state.mode = "auto";
    dashboard.state.prompt = "Summarize my pipeline";
    await dashboard.sendPrompt();
    expect(calls).toEqual([
        ["ai.agent.ask", "create", [{ agent_id: 7, prompt: "Summarize my pipeline", attachment_ids: [[6, 0, []]] }]],
        ["ai.agent.ask", "action_send", [[11]]],
    ]);
    expect(opened.res_model).toBe("ai.agent.conversation");
    expect(dashboard.state.prompt).toBe("");
});
