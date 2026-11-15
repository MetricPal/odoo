import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { beforeEach, expect, test } from "@odoo/hoot";
import { mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";

import { countChars } from "@marketing_intel_research/chat_research";
import { ResearchBanners } from "@marketing_intel_research/research_desk";

defineMailModels();

let desk;

beforeEach(() => {
    desk = {
        brands: [{ id: 3, name: "Green Corner" }], assistant: true, web: true, ai_manager: false,
        ai_agent_action: false, profile_id: false, max: 1000, examples: [],
    };
    mockService("orm", { call: async () => desk });
});

test("counts characters as people do", () => {
    expect(countChars("plants 🌱")).toBe(8);
});

test("no banner when the assistant is ready and searches the web", async () => {
    await mountWithCleanup(ResearchBanners);
    expect(".o_mi_research_banner").toHaveCount(0);
});

test("web search off: who switches it on", async () => {
    desk.web = false;
    await mountWithCleanup(ResearchBanners);
    expect(".alert-warning").toHaveText(/Web search is off for the Marketing assistant/);
    expect(".alert-warning").toHaveText(/Ask an AI Agent manager to switch it on/);
    expect(".alert-warning a").toHaveCount(0);
});

test("web search off, for an AI Agent manager: Open the profile", async () => {
    Object.assign(desk, { web: false, ai_manager: true });
    await mountWithCleanup(ResearchBanners);
    expect(".alert-warning a").toHaveText("Open the profile");
});

test("no assistant ready", async () => {
    desk.assistant = false;
    await mountWithCleanup(ResearchBanners);
    expect(".alert-danger").toHaveText(/No Marketing assistant is ready/);
});
