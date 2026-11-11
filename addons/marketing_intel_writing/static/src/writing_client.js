import { _t } from "@web/core/l10n/translation";

export const POLL_MS = 1500;
const WAIT_MAX_MS = 5 * 60 * 1000;

/** Names of the tools, the same in every menu and suggestion (boards 8.1 to 8.4). */
export function toolLabel(tool, option, languages = []) {
    switch (tool) {
        case "rewrite": return _t("Rewrite");
        case "shorter": return _t("Shorter");
        case "longer": return _t("Longer");
        case "tone": return _t("Tone · %s", TONES().find(([value]) => value === option)?.[1] || "");
        case "translate": return _t("Translate · %s", languages.find(([code]) => code === option)?.[1] || option);
        case "grammar": return _t("Fix grammar");
        case "hashtags": return _t("Hashtags");
        case "fit": return _t("Fit to the channel");
        case "subjects": return _t("Subject lines");
        case "custom": return _t("Your request");
    }
    return tool;
}

export function TONES() {
    return [["friendly", _t("Friendly")], ["formal", _t("Formal")], ["bold", _t("Bold")]];
}

/** Characters as people count them (an emoji is one). */
export function countChars(text) {
    return [...(text || "")].length;
}

/**
 * One suggestion: ask the marketing agent, then follow the run until it has an answer.
 * `onUpdate` receives {state: "waiting" | "ready" | "failed", ...}.
 */
export class SuggestionRequest {
    constructor(orm, onUpdate) {
        this.orm = orm;
        this.onUpdate = onUpdate;
        this.runId = false;
        this.timer = null;
        this.cancelled = false;
        this.original = "";
    }

    async start({ resModel, field, resId, tool, text, option, values }) {
        this.cancel();
        this.cancelled = false;
        this.original = text || "";
        this.startedAt = Date.now();
        this.onUpdate({ state: "waiting" });
        try {
            this.runId = await this.orm.call("mi.writing", "ask",
                [resModel, field, resId || false, tool, text || "", option || false, values || {}]);
        } catch (error) {
            this.onUpdate({ state: "failed", error: error.data?.message || error.message });
            return;
        }
        if (!this.cancelled) {
            this.schedule();
        }
    }

    schedule() {
        this.timer = setTimeout(() => this.poll(), POLL_MS);
    }

    async poll() {
        this.timer = null;
        if (this.cancelled || !this.runId) {
            return;
        }
        let result;
        try {
            result = await this.orm.call("mi.writing", "get_suggestion", [this.runId, this.original]);
        } catch (error) {
            result = { state: "failed", error: error.data?.message || error.message };
        }
        if (this.cancelled) {
            return;
        }
        if (result.state === "waiting") {
            if (Date.now() - this.startedAt > WAIT_MAX_MS) {
                this.onUpdate({ state: "failed", error: _t("The assistant is taking too long. Try again later.") });
                return;
            }
            this.schedule();
            return;
        }
        this.onUpdate(result);
    }

    /** Stop following; a run still waiting is stopped too, so it does not use the assistant for nothing. */
    cancel() {
        this.cancelled = true;
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
            if (this.runId) {
                this.orm.call("mi.writing", "stop", [this.runId]).catch(() => {});
            }
        }
        this.runId = false;
    }
}
