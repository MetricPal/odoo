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
} from "@ai_home/dashboard/dashboard";

defineMailModels();

const now = () => luxon.DateTime.utc().toFormat("yyyy-MM-dd HH:mm:ss");

function attentionRow(category, id, extra = {}) {
    return {
        key: `${category}-${id}`,
        category,
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

function homeData() {
    return {
        firstName: "Aisha",
        roleLabel: "Operations manager",
        summary: "3 items need you, 1 overdue",
        live: [
            { key: "approvals", label: "Approvals pending", value: "7", sub: "2 overdue", tone: "warn",
              action: { type: "ir.actions.act_window", res_model: "approval.center.request" } },
            { key: "team", label: "Team online", value: "9 / 12", sub: "2 on leave", tone: "good", action: false },
        ],
        attention: [
            attentionRow("approval", 1, { tag: "Overdue", overdue: true }),
            attentionRow("conversation", 2, {
                model: "omni.conversation",
                primary: { label: "Assign to me", method: "action_assign_me" },
                secondary: { label: "Open", open: true },
            }),
            attentionRow("ai", 3, { model: "ai.agent.run", primary: { label: "Review", open: true }, secondary: false }),
        ],
        feed: [
            { key: "f1", occurred: now(), actor: "You", text: "approved PO/2026/0139", app: "Approvals",
              scope: "mine", model: "approval.center.request", resId: 9 },
            { key: "f2", occurred: now(), actor: "Omar Haddad", text: "approved EXP/0931", app: "Approvals",
              scope: "team", model: "approval.center.request", resId: 8 },
            { key: "f3", occurred: now(), actor: "Workflow", text: "assigned 18 new leads", app: "Workflow",
              scope: "all", model: "crm.lead", resId: 7 },
        ],
        day: [{ key: "due", time: "Today", text: "3 tasks due", model: false, resId: false }],
        recent: [{ key: "r1", name: "PO/2026/0142", app: "Approvals", model: "approval.center.request", resId: 1 }],
        quickActions: [{ key: "res.partner", label: "Contact", model: "res.partner", context: {} }],
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

test("helpers: filter chips and feed scopes", () => {
    const tabs = categoryTabs(homeData().attention);
    expect(tabs.map((tab) => `${tab.key} ${tab.count}`)).toEqual([
        "all 3",
        "approval 1",
        "conversation 1",
        "ai 1",
    ]);
    const feed = homeData().feed;
    expect(feedForScope(feed, "mine").map((entry) => entry.key)).toEqual(["f1"]);
    expect(feedForScope(feed, "team").map((entry) => entry.key)).toEqual(["f1", "f2"]);
    expect(feedForScope(feed, "all")).toHaveLength(3);
});

test("renders the design's sections", async () => {
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_greeting h1").toHaveText(/, Aisha$/);
    expect(".o_ai_home_greeting span").toHaveText(/Operations manager · 3 items need you, 1 overdue$/);
    expect(".o_ai_home_tile").toHaveCount(2);
    expect(".o_ai_home_tile.o_tone_warn .o_ai_home_tile_value").toHaveText("7");
    expect(".o_ai_home_attention_row").toHaveCount(3);
    expect(".o_ai_home_attention_row:first .o_ai_home_tag").toHaveText("Overdue");
    expect(".o_ai_home_attention_row:first .o_ai_home_badge").toHaveText("AP");
    expect(".o_ai_home_feed_row").toHaveCount(3);
    expect(".o_ai_home_day_row .o_ai_home_day_time").toHaveText("Today");
    expect(".o_ai_home_recent_row").toHaveCount(1);
    // No assistant for this user: quick actions instead of the assistant box.
    expect(".o_ai_home_quick_btn").toHaveText("+ Contact");
    expect(".o_ai_home_ask").toHaveCount(0);
});

test("chips filter the list and scopes filter the feed", async () => {
    await mountWithCleanup(WorkDashboard);
    await contains('.o_ai_home_chip:contains("Conversations")').click();
    expect(".o_ai_home_attention_row").toHaveCount(1);
    expect(".o_ai_home_attention_row .o_ai_home_btn_primary").toHaveText("Assign to me");
    await contains('.o_ai_home_segment:contains("Mine")').click();
    expect(".o_ai_home_feed_row").toHaveCount(1);
    await contains('.o_ai_home_segment:contains("My team")').click();
    expect(".o_ai_home_feed_row").toHaveCount(2);
});

test("buttons run on the server, then Home reloads; open buttons open the record", async () => {
    await mountWithCleanup(WorkDashboard);
    calls = [];
    await contains(".o_ai_home_attention_row:first .o_ai_home_btn_primary").click();
    expect(calls[0]).toEqual(["run_home_action", ["approval.center.request", 1, "action_approve"]]);
    expect(calls[1][0]).toBe("get_home_data");
    calls = [];
    await contains('.o_ai_home_attention_row .o_ai_home_btn_primary:contains("Review")').click();
    expect(calls).toEqual([
        ["doAction", {
            type: "ir.actions.act_window",
            res_model: "ai.agent.run",
            res_id: 3,
            views: [[false, "form"]],
            target: "current",
        }],
    ]);
});

test("tiles with a list open it", async () => {
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_tile:last").toHaveAttribute("disabled");
    await contains(".o_ai_home_tile:first").click();
    expect(calls.at(-1)).toEqual(["doAction", data.live[0].action]);
});

test("the assistant answers on Home and keeps the conversation", async () => {
    data.agents = [{ id: 7, name: "Ops Assistant", description: "" }];
    data.prompts = ["What needs my approval today?"];
    data.quickActions = [];
    browser.localStorage.removeItem("ai_home.agent");
    await mountWithCleanup(WorkDashboard);
    expect(".o_ai_home_quick").toHaveCount(0);
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
