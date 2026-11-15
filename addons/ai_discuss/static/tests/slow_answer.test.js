import { describe, expect, test } from "@odoo/hoot";

import { ASSISTANT_TYPING_MS, slowAnswerStatus } from "@ai_discuss/slow_answer_patch";

describe.current.tags("desktop");

test("a slow answer is a status that grows with the wait (owner, 2026-11-13)", () => {
    expect(slowAnswerStatus(0)).toBe(null);
    expect(slowAnswerStatus(9)).toBe(null);
    expect(slowAnswerStatus(10)).toBe("This is taking a bit longer than usual…");
    expect(slowAnswerStatus(29)).toBe("This is taking a bit longer than usual…");
    expect(slowAnswerStatus(30)).toBe("Still working on it; the AI service is slow right now.");
    expect(slowAnswerStatus(59)).toBe("Still working on it; the AI service is slow right now.");
    expect(slowAnswerStatus(60)).toBe("Still working on it; the AI service is slow right now (1 min).");
    expect(slowAnswerStatus(150)).toBe("Still working on it; the AI service is slow right now (2 min).");
});

test("the assistant keeps typing as long as the ERP allows a question", () => {
    expect(ASSISTANT_TYPING_MS).toBeGreaterThan(15 * 60 * 1000);
});
