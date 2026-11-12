import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { beforeEach, expect, test } from "@odoo/hoot";
import { advanceTime, animationFrame } from "@odoo/hoot-dom";
import { proxy } from "@odoo/owl";
import { contains, mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";

import { WritingTools, htmlToText } from "@marketing_intel_writing/writing_tools";
import { POLL_MS, countChars, toolLabel } from "@marketing_intel_writing/writing_client";

defineMailModels();

const TOOLS = {
    available: true, kind: "messaging", agent: "Marketing Assistant",
    tools: ["rewrite", "shorter", "longer", "tone", "translate", "grammar", "fit", "custom"],
    languages: [["en_US", "English (US)"], ["nl_NL", "Dutch"]], ab_test: false,
};

let calls;
let answers;

function makeRecord(data = {}, resModel = "mm.mailing") {
    const record = {
        resModel, resId: 7, isDirty: false,
        fields: { channel: { selection: [["whatsapp", "WhatsApp"], ["telegram", "Telegram"]] } },
        data: proxy({ body: "Hi {first_name}, spring is here!", channel: "whatsapp", char_limit: 1024, ...data }),
        update: async (values) => {
            expect.step(`update:${Object.entries(values).map(([k, v]) => `${k}=${v}`).join(",")}`);
            Object.assign(record.data, values);
        },
        save: async () => true,
        load: async () => {},
    };
    return record;
}

beforeEach(() => {
    calls = [];
    answers = [];
    mockService("notification", { add: (message) => expect.step(`notify:${message}`) });
    mockService("orm", {
        async call(model, method, args) {
            expect(model).toBe("mi.writing");
            calls.push([method, args]);
            if (method === "get_tools") {
                if (args[0] === "res.partner") {
                    return { available: false };
                }
                if (args[0] === "mailing.mailing") {
                    return {
                        ...TOOLS, kind: "email_subject", tools: ["subjects", ...TOOLS.tools], ab_test: true,
                        limit: 78, soft: true, limit_note: "The email standard (RFC 5322) recommends at most 78.",
                    };
                }
                return TOOLS;
            }
            if (method === "ask") {
                return 42;
            }
            if (method === "get_suggestion") {
                return answers.shift() || { state: "waiting" };
            }
            return true;
        },
    });
});

test("helpers: labels, characters and email text", async () => {
    // Labels are translated: mount once so the translations are loaded.
    await mountWithCleanup(WritingTools, { props: { record: makeRecord({}, "res.partner"), field: "comment" } });
    expect(String(toolLabel("translate", "nl_NL", TOOLS.languages))).toBe("Translate · Dutch");
    expect(String(toolLabel("tone", "bold"))).toBe("Tone · Bold");
    expect(countChars("héllo 👋")).toBe(7);
    expect(htmlToText("<p>Spring</p><p>is here</p>")).toMatch(/Spring\s*is here/);
});

test("the email subject shows n / 78, orange past the recommended length", async () => {
    const record = makeRecord({ subject: "Our spring offer" }, "mailing.mailing");
    await mountWithCleanup(WritingTools, { props: { record, field: "subject" } });
    expect(".o_mi_writing_box_count").toHaveText("16 / 78");
    expect(".o_mi_writing_box_count").toHaveClass("text-muted");
    record.data.subject = "x".repeat(79);
    await animationFrame();
    expect(".o_mi_writing_box_count").toHaveText("79 / 78");
    expect(".o_mi_writing_box_count").toHaveClass("text-warning");
    expect(".o_mi_writing_box_count").toHaveAttribute("title", /RFC 5322/);
});

test("an SMS counts 160 per message, 70 once it needs Unicode", async () => {
    mockService("orm", {
        async call(model, method) {
            return method === "get_tools" ? { ...TOOLS, kind: "sms" } : true;
        },
    });
    const record = makeRecord({ body_plaintext: "Spring offer" }, "mailing.mailing");
    await mountWithCleanup(WritingTools, { props: { record, field: "body_plaintext" } });
    expect(".o_mi_writing_box_count").toHaveText("12 / 160 · 1 SMS");
    record.data.body_plaintext = "Весеннее предложение";
    await animationFrame();
    expect(".o_mi_writing_box_count").toHaveText("20 / 70 · 1 SMS");
});

test("no ✦ when the assistant is not available", async () => {
    await mountWithCleanup(WritingTools, { props: { record: makeRecord({}, "res.partner"), field: "comment" } });
    expect(".o_mi_writing_button").toHaveCount(0);
});

test("the box shows the channel's count in its corner", async () => {
    await mountWithCleanup(WritingTools, { props: { record: makeRecord(), field: "body" } });
    expect(".o_mi_writing_box_count").toHaveText("32 / 1,024");
    expect(".o_mi_writing_box_count").toHaveClass("text-muted");
});

test("a tool asks, waits, shows the suggestion and Use puts it in the field", async () => {
    const record = makeRecord();
    await mountWithCleanup(WritingTools, { props: { record, field: "body" } });
    await contains(".o_mi_writing_button").click();
    await contains(".o_mi_writing_tool:contains(Shorter)").click();
    expect(calls.find(([method]) => method === "ask")[1]).toEqual(
        ["mm.mailing", "body", 7, "shorter", "Hi {first_name}, spring is here!", false, { channel: "whatsapp" }]);
    expect(".o_mi_writing_card").toHaveText(/Writing/);
    expect(record.data.body).toBe("Hi {first_name}, spring is here!", { message: "nothing replaced yet" });

    answers.push({ state: "ready", text: "Hi {first_name}! Spring is here.", warning: "" });
    await advanceTime(POLL_MS + 10);
    await animationFrame();
    expect(".o_mi_writing_title").toHaveText("Shorter");
    expect(".o_mi_writing_text").toHaveText("Hi {first_name}! Spring is here.");
    expect(".o_mi_writing_count").toHaveText("32 / 1,024");

    await contains(".o_mi_writing_card button:contains(Use)").click();
    expect.verifySteps(["update:body=Hi {first_name}! Spring is here."]);
    expect(".o_mi_writing_card").toHaveCount(0);
});

test("Fit is named after the channel, and Discard keeps the text", async () => {
    const record = makeRecord();
    await mountWithCleanup(WritingTools, { props: { record, field: "body" } });
    await contains(".o_mi_writing_button").click();
    expect(".o_mi_writing_tool:contains(Fit to WhatsApp)").toHaveCount(1);
    await contains(".o_mi_writing_tool:contains(Fit to WhatsApp)").click();
    answers.push({ state: "ready", text: "Short", warning: "" });
    await advanceTime(POLL_MS + 10);
    await animationFrame();
    await contains(".o_mi_writing_card button:contains(Discard)").click();
    expect(".o_mi_writing_card").toHaveCount(0);
    expect(record.data.body).toBe("Hi {first_name}, spring is here!");
    expect.verifySteps([]);
});

test("a failed suggestion shows the reason and can be tried again", async () => {
    await mountWithCleanup(WritingTools, { props: { record: makeRecord(), field: "body" } });
    await contains(".o_mi_writing_button").click();
    await contains(".o_mi_writing_tool:contains(Rewrite)").click();
    answers.push({ state: "failed", error: "Model quota exhausted" });
    await advanceTime(POLL_MS + 10);
    await animationFrame();
    expect(".o_mi_writing_card .alert").toHaveText("Model quota exhausted");
    await contains(".o_mi_writing_card button:contains(Try again)").click();
    expect(calls.filter(([method]) => method === "ask")).toHaveLength(2);
});

test("Ask something else sends the person's instruction", async () => {
    await mountWithCleanup(WritingTools, { props: { record: makeRecord(), field: "body" } });
    await contains(".o_mi_writing_button").click();
    await contains(".o_mi_writing_custom").click();
    await contains(".o_mi_writing_custom_input").edit("Mention Sunday opening", { confirm: false });
    await contains(".o_mi_writing_card button:contains(Ask)").click();
    const ask = calls.find(([method]) => method === "ask")[1];
    expect(ask[3]).toBe("custom");
    expect(ask[5]).toBe("Mention Sunday opening");
});

test("subject lines: the email body goes with the request, and each line has Use and A/B test it", async () => {
    const record = makeRecord({ subject: "Our spring offer", body_html: "<p>Every plant 20% off</p>" }, "mailing.mailing");
    await mountWithCleanup(WritingTools, { props: { record, field: "subject", compact: true } });
    await contains(".o_mi_writing_button").click();
    await contains(".o_mi_writing_tool:contains(Subject lines)").click();
    const ask = calls.find(([method]) => method === "ask")[1];
    expect(ask[3]).toBe("subjects");
    expect(ask[6].body_text).toMatch(/Every plant 20% off/);
    answers.push({ state: "ready", text: "", lines: ["20% off every plant", "Spring is here"], warning: "" });
    await advanceTime(POLL_MS + 10);
    await animationFrame();
    expect(".o_mi_writing_line").toHaveCount(2);
    expect(".o_mi_writing_line:first button:contains(A/B test it)").toHaveCount(1);
    await contains(".o_mi_writing_line:last button:contains(Use)").click();
    expect.verifySteps(["update:subject=Spring is here"]);
});

test("an empty text asks the person to write first", async () => {
    await mountWithCleanup(WritingTools, { props: { record: makeRecord({ body: "" }), field: "body" } });
    await contains(".o_mi_writing_button").click();
    await contains(".o_mi_writing_tool:contains(Rewrite)").click();
    expect.verifySteps(["notify:Write some text first."]);
    expect(calls.filter(([method]) => method === "ask")).toHaveLength(0);
});
