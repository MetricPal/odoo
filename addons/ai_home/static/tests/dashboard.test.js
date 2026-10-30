import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { beforeEach, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame } from "@odoo/hoot-dom";
import { browser } from "@web/core/browser/browser";
import { user } from "@web/core/user";
import { contains, mockService, mountWithCleanup, patchWithCleanup } from "@web/../tests/web_test_helpers";

import {
    WorkDashboard,
    categoryTabs,
    feedForScope,
    planApps,
    planSections,
} from "@ai_home/dashboard/dashboard";

defineMailModels();

const now = () => luxon.DateTime.utc().toFormat("yyyy-MM-dd HH:mm:ss");

function attentionRow(category, id, extra = {}) {
    return {
        key: `${category}-${id}`,
        category,
        badge: category === "approval" ? "AP" : "OC",
        model: "approval.center.request",
        resId: id,
        openAction: false,
        title: `${category} ${id}`,
        meta: "Approvals · requested by Daniel Tan · waiting 2 days",
        tag: "",
        overdue: false,
        occurred: now(),
        primary: { label: "Approve", method: "action_approve" },
        secondary: { label: "Reject", method: "action_refuse" },
        ...extra,
    };
}

let data;
let calls;

function planRow(key, section, extra = {}) {
    return {
        key,
        kind: "activity",
        section,
        title: key,
        meta: "Tan Holdings · due today",
        note: "",
        app: "CRM",
        icon: "call",
        time: "",
        date: "2026-10-30",
        model: "mail.activity",
        resId: 40,
        openModel: "crm.lead",
        openId: 4,
        canDone: true,
        joinUrl: false,
        ...extra,
    };
}

function homeData() {
    return {
        today: { done: 4, late: 2, todo: 3, total: 9, label: "Fri 30 Oct" },
        week: [
            { date: "2026-10-30", label: "Fri", longLabel: "Friday 30 Oct", count: 5, heavy: false, isToday: true },
            { date: "2026-10-31", label: "Sat", longLabel: "Saturday 31 Oct", count: 12, heavy: true, isToday: false },
        ],
        plan: [
            planRow("Send contract", "late", { meta: "Enrique · 27 days late" }),
            planRow("Demo Lim", "today", { kind: "meeting", time: "10:00", app: "Calendar", canDone: false,
                                           joinUrl: "https://meet.example/1", model: "calendar.event", resId: 3,
                                           openModel: "calendar.event", openId: 3 }),
            planRow("Call back Tan", "today", { resId: 41 }),
            planRow("Prepare drafts", "tomorrow", { app: "Project" }),
        ],
        waiting: [
            { key: "waiting-activity-50", who: "Mei Wong", initials: "MW", title: "Mei · Send contract",
              meta: "Tan Holdings · 3 days late", tone: "bad", since: "2026-10-27", model: "mail.activity", resId: 50,
              openModel: "res.partner", openId: 9, nudge: { label: "Nudge", method: "home_nudge" } },
        ],
        team: [],
        attention: [
            attentionRow("approval", 1, { tag: "Overdue", overdue: true }),
            attentionRow("conversation", 2, {
                model: "omni.conversation",
                primary: { label: "Assign to me", method: "action_assign_me" },
                secondary: { label: "Open", open: true },
            }),
            attentionRow("source_7", 3, { model: "hr.leave", badge: "TO", primary: { label: "Approve", method: "action_approve" } }),
        ],
        attentionGroups: [
            { key: "approval", label: "Approvals", count: 1, shown: 1, action: false },
            { key: "conversation", label: "Conversations", count: 1, shown: 1, action: false },
            { key: "source_7", label: "Time Off", count: 8, shown: 1,
              action: { type: "ir.actions.act_window", res_model: "hr.leave", domain: [["id", "in", [3]]] } },
        ],
        feed: [
            { key: "f1", occurred: now(), actor: "Mei Wong", text: "mentioned you in SO/2231", app: "Sales",
              forMe: true, team: true, model: "sale.order", resId: 9 },
            { key: "f2", occurred: now(), actor: "Omar Haddad", text: "approved EXP/0931", app: "Approvals",
              forMe: false, team: true, model: "approval.center.request", resId: 8 },
            { key: "f3", occurred: now(), actor: "Workflow", text: "assigned 18 new leads", app: "Workflow",
              forMe: false, team: false, model: "crm.lead", resId: 7 },
        ],
        recent: [{ key: "r1", name: "PO/2026/0142", app: "Approvals", model: "approval.center.request", resId: 1,
                   occurred: now() }],
        agents: [],
        prompts: [],
        canManageAgents: false,
    };
}

beforeEach(() => {
    data = homeData();
    calls = [];
    patchWithCleanup(user, { userId: 42 });
    mockService("notification", { add: () => {} });
    mockService("action", { doAction: (action) => calls.push(["doAction", action]) });
    mockService("orm", {
        async call(model, method, args) {
            expect(model).toBe("ai.home.item");
            calls.push([method, args]);
            if (method === "get_home_data") {
                return data;
            }
            if (method === "ask_ai") {
                return { runId: 5, conversationId: 11 };
            }
            if (method === "get_ai_answer") {
                return { state: "completed", answer: "You have 3 approvals waiting.", error: "", conversationId: 11 };
            }
            return true;
        },
        create: async () => [99],
        unlink: async () => true,
    });
});

test("helpers: chips, plan sections and feed scopes", () => {
    const data = homeData();
    const tabs = categoryTabs(data.attentionGroups, data.attention.length);
    expect(tabs.map((tab) => `${tab.key} ${tab.count}`)).toEqual([
        "all 3",
        "approval 1",
        "conversation 1",
        "source_7 8",
    ]);
    expect(planApps(data.plan).map((tab) => `${tab.key} ${tab.count}`)).toEqual([
        "all 4",
        "CRM 2",
        "Calendar 1",
        "Project 1",
    ]);
    expect(planSections(data.plan).map((section) => `${section.key} ${section.items.length}`)).toEqual([
        "late 1",
        "today 2",
        "tomorrow 1",
    ]);
    expect(planSections(data.plan, "Project").map((section) => section.key)).toEqual(["tomorrow"]);
    const feed = data.feed;
    expect(feedForScope(feed, "forMe").map((entry) => entry.key)).toEqual(["f1"]);
    expect(feedForScope(feed, "team").map((entry) => entry.key)).toEqual(["f1", "f2"]);
    expect(feedForScope(feed, "all")).toHaveLength(3);
});

test("renders my plan, decisions and what others did", async () => {
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_tile").toHaveCount(0);
    expect(".o_ai_home_day").toHaveCount(0);
    expect(".o_ai_home_ring_value").toHaveText("4/9");
    expect(".o_ai_home_today_counts li:first").toHaveText("2 late");
    expect(".o_ai_home_week_bar").toHaveCount(2);
    expect(".o_ai_home_week_bar.o_is_heavy").toHaveCount(1);
    // Late and Today are open, Tomorrow is folded.
    expect(".o_ai_home_plan_section").toHaveCount(3);
    expect(".o_ai_home_plan_row").toHaveCount(3);
    expect(".o_section_late .o_ai_home_section_head").toHaveText(/late · 1/i);
    expect(".o_ai_home_plan_row.o_is_meeting .o_ai_home_plan_time").toHaveText("10:00");
    expect(".o_ai_home_plan_row.o_is_meeting .o_ai_home_join").toHaveCount(1);
    expect(".o_ai_home_plan_row.o_is_meeting .o_ai_home_done").toHaveCount(0);
    expect(".o_ai_home_waiting_row").toHaveCount(1);
    expect(".o_ai_home_waiting_meta").toHaveClass("o_tone_bad");
    expect(".o_ai_home_team").toHaveCount(0);
    expect(".o_ai_home_attention_row").toHaveCount(3);
    expect(".o_ai_home_attention_row:first .o_ai_home_tag").toHaveText("Overdue");
    expect(".o_ai_home_attention_row:first .o_ai_home_badge").toHaveText("AP");
    expect(".o_ai_home_badge.o_cat_source").toHaveText("TO");
    expect(".o_ai_home_open_group").toHaveCount(0);
    // For me is the first tab and ends with the inbox link.
    expect(".o_ai_home_feed_row").toHaveCount(1);
    expect(".o_ai_home_inbox").toHaveText("Open inbox →");
    expect(".o_ai_home_recent_list").toHaveCount(0);
    expect(".o_ai_home_recent_summary").toHaveText(/PO\/2026\/0142/);
    await contains(".o_ai_home_recent_toggle").click();
    expect(".o_ai_home_recent_row .o_ai_home_pill").toHaveText("Approvals");
    expect(".o_ai_home_recent_date").toHaveText("Today");
    // No assistant for this user: the box stays, disabled, and says how to get one.
    expect(".o_ai_home_ask").toHaveClass("o_is_unavailable");
    expect("#ai_home_prompt").toHaveAttribute("disabled");
    expect("#ai_home_prompt").toHaveAttribute("placeholder", /No assistant is available to you yet/);
});

test("chips filter the lists and sections fold", async () => {
    await mountWithCleanup(WorkDashboard);
    await contains('.o_ai_home_attention .o_ai_home_chip:contains("Time Off")').click();
    expect(".o_ai_home_attention_row").toHaveCount(1);
    expect(".o_ai_home_open_group").toHaveText("Open all in Time Off →");
    expect(".o_ai_home_more").toHaveText("+ 7 more in Time Off →");
    await contains(".o_ai_home_open_group").click();
    expect(calls.at(-1)).toEqual(["doAction", data.attentionGroups[2].action]);
    await contains('.o_ai_home_plan_apps .o_ai_home_chip:contains("Project")').click();
    expect(".o_ai_home_plan_section").toHaveCount(1);
    await contains(".o_ai_home_plan_section .o_ai_home_section_head").click();
    expect(".o_ai_home_plan_row").toHaveCount(1);
    await contains('.o_ai_home_segment:contains("My team")').click();
    expect(".o_ai_home_feed_row").toHaveCount(2);
    expect(".o_ai_home_inbox").toHaveCount(0);
});

test("plan buttons run on the server, rows open the document", async () => {
    await mountWithCleanup(WorkDashboard);
    calls = [];
    // Row buttons show on hover; the test clicks them directly.
    await contains('.o_ai_home_plan_row:contains("Call back Tan") .o_ai_home_done', { visible: false }).click();
    expect(calls[0]).toEqual(["run_home_action", ["mail.activity", 41, "action_done"]]);
    expect(calls[1][0]).toBe("get_home_data");
    calls = [];
    await contains('.o_ai_home_plan_row:contains("Call back Tan") .o_ai_home_snooze_toggle', { visible: false }).click();
    await contains('.o_ai_home_snooze_menu .dropdown-item:contains("Next week")').click();
    expect(calls[0]).toEqual(["run_home_action", ["mail.activity", 41, "action_reschedule_nextweek"]]);
    calls = [];
    await contains('.o_ai_home_plan_row:contains("Send contract") .o_ai_home_plan_open').click();
    expect(calls).toEqual([
        ["doAction", {
            type: "ir.actions.act_window",
            res_model: "crm.lead",
            res_id: 4,
            views: [[false, "form"]],
            target: "current",
        }],
    ]);
    calls = [];
    await contains(".o_ai_home_nudge").click();
    expect(calls[0]).toEqual(["run_home_action", ["mail.activity", 50, "home_nudge"]]);
    calls = [];
    await contains(".o_ai_home_attention_row:first .o_ai_home_btn_primary").click();
    expect(calls[0]).toEqual(["run_home_action", ["approval.center.request", 1, "action_approve"]]);
});

test("managers see their team's load", async () => {
    data.team = [
        { key: "team-5", name: "Mei Wong", initials: "MW", userId: 5, late: 6, today: 8, open: 20, load: 100, tone: "bad" },
        { key: "team-6", name: "Aina Ismail", initials: "AI", userId: 6, late: 0, today: 3, open: 5, load: 25, tone: "good" },
    ];
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_team_row").toHaveCount(2);
    expect(".o_ai_home_team_row:first .o_ai_home_team_late").toHaveText("6");
    await contains(".o_ai_home_team_row:first").click();
    expect(calls.at(-1)[1].domain).toEqual([["user_id", "=", 5]]);
});

test("the assistant answers on Home and keeps the conversation", async () => {
    data.agents = [{ id: 7, name: "Ops Assistant", description: "" }];
    data.prompts = ["What needs my approval today?"];
    browser.localStorage.removeItem("ai_home.agent");
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_ask").not.toHaveClass("o_is_unavailable");
    expect(".o_ai_home_agent_toggle").toHaveText("Ops Assistant ▾");
    expect(".o_ai_home_rights").toHaveText("Uses your access rights");
    expect(".o_ai_home_send").toHaveAttribute("disabled");
    await contains(".o_ai_home_prompt").click();
    expect(calls.find(([method]) => method === "ask_ai")[1]).toEqual([7, "What needs my approval today?", [], false]);
    await animationFrame();
    expect(".o_ai_home_chat_question").toHaveText("What needs my approval today?");
    expect(".o_ai_home_chat_text").toHaveText("You have 3 approvals waiting.");
    expect(".o_ai_home_prompts").toHaveCount(0);
    // A follow-up goes to the same conversation.
    await contains("#ai_home_prompt").edit("And tomorrow?");
    await contains(".o_ai_home_send").click();
    expect(calls.filter(([method]) => method === "ask_ai").at(-1)[1]).toEqual([7, "And tomorrow?", [], 11]);
    await animationFrame();
    await contains(".o_ai_home_chat_action").click();
    expect(calls.at(-1)[1].res_model).toBe("ai.agent.conversation");
    await contains(".o_ai_home_chat_close").click();
    expect(".o_ai_home_chat").toHaveCount(0);
    expect(".o_ai_home_prompt").toHaveCount(1);
});

test("Home refreshes by itself", async () => {
    await mountWithCleanup(WorkDashboard);
    const before = calls.filter(([method]) => method === "get_home_data").length;
    await advanceTime(60000);
    expect(calls.filter(([method]) => method === "get_home_data").length).toBe(before + 1);
});
