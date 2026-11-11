import { Component, onWillDestroy, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { countSMS, extractSmsEncoding } from "@sms/core/sms_char_counter_utils";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

import { SuggestionRequest, TONES, countChars, toolLabel } from "./writing_client";

const TEXT_MAX = 6000;

/** Plain text of an email body, for the subject lines. */
export function htmlToText(html) {
    if (!html) {
        return "";
    }
    const doc = new DOMParser().parseFromString(String(html), "text/html");
    return (doc.body.innerText || doc.body.textContent || "").replace(/\n{3,}/g, "\n\n").trim().slice(0, TEXT_MAX);
}

/**
 * Writing tools under a marketing text (approved boards 8.1 to 8.4): a menu of tools, then the assistant's
 * suggestion under the text with Use / Try again / Discard. The text changes only on Use.
 */
export class WritingTools extends Component {
    static template = "marketing_intel_writing.WritingTools";
    static components = { Dropdown, DropdownItem };
    props = useProps({
        ...standardWidgetProps,
        field: t.string(),
        compact: t.boolean().optional(false),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({
            tools: null, suggestion: null, customOpen: false, customText: "", lastRequest: null, abBusy: false,
        });
        this.request = new SuggestionRequest(this.orm, (result) => this.onResult(result));
        onWillStart(async () => {
            this.state.tools = await this.orm.call("mi.writing", "get_tools",
                [this.props.record.resModel, this.props.field]);
        });
        onWillDestroy(() => this.request.cancel());
    }

    get record() { return this.props.record; }
    get tools() { return this.state.tools || { available: false, tools: [] }; }
    get kind() { return this.tools.kind; }
    get text() { return this.record.data[this.props.field] || ""; }
    has(tool) { return this.tools.tools.includes(tool); }
    get tones() { return TONES(); }
    chars(text) { return countChars(text); }

    /** Form values the server needs for the channel's limit (nothing is saved). */
    get values() {
        const data = this.record.data;
        const values = {};
        if (data.channel) { values.channel = data.channel; }
        if (data.operation) { values.operation = data.operation; }
        if (data.connection_id) { values.connection_id = data.connection_id.id || data.connection_id; }
        if (this.kind === "email_subject") { values.body_text = htmlToText(data.body_html || data.body_arch); }
        return values;
    }

    get fitLabel() {
        switch (this.kind) {
            case "sms": return _t("Fit to one SMS");
            case "messaging": return _t("Fit to %s", this.channelLabel || _t("the channel"));
            case "social": return _t("Fit to %s", this.platformLabel || _t("the platform"));
        }
        return _t("Fit to the channel");
    }
    get channelLabel() {
        const field = this.record.fields.channel;
        return field?.selection?.find(([value]) => value === this.record.data.channel)?.[1] || "";
    }
    get platformLabel() {
        return this.record.data.composer_ui?.platform?.label || "";
    }
    label(tool, option) {
        return tool === "fit" ? this.fitLabel : toolLabel(tool, option, this.tools.languages);
    }

    ask(tool, option = false) {
        if (tool !== "subjects" && !this.text.trim()) {
            this.notification.add(_t("Write some text first."), { type: "warning" });
            return;
        }
        this.state.customOpen = false;
        this.state.lastRequest = { tool, option, original: this.text };
        this.state.suggestion = { tool, option, state: "waiting" };
        this.request.start({
            resModel: this.record.resModel, field: this.props.field, resId: this.record.resId, tool,
            text: tool === "subjects" ? "" : this.text, option, values: this.values,
        });
    }
    onResult(result) {
        if (!this.state.suggestion) {
            return;
        }
        Object.assign(this.state.suggestion, { text: "", lines: [], warning: "", error: "" }, result);
    }
    openCustom() {
        this.request.cancel();
        this.state.suggestion = null;
        this.state.customOpen = true;
    }
    onCustomKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.askCustom();
        }
    }
    askCustom() {
        const instruction = this.state.customText.trim();
        if (!instruction) {
            return;
        }
        this.ask("custom", instruction);
    }
    tryAgain() {
        const last = this.state.lastRequest;
        if (last) {
            this.ask(last.tool, last.option);
        }
    }
    discard() {
        this.request.cancel();
        this.state.suggestion = null;
        this.state.customOpen = false;
    }
    async use(text) {
        await this.record.update({ [this.props.field]: text });
        this.state.suggestion = null;
    }
    async abTest(subject) {
        if (this.state.abBusy) {
            return;
        }
        if (!this.record.resId || this.record.isDirty) {
            const saved = await this.record.save();
            if (saved === false || !this.record.resId) {
                return;
            }
        }
        this.state.abBusy = true;
        try {
            const copy = await this.orm.call("mi.writing", "ab_test_subject", [this.record.resId, subject]);
            await this.record.load();
            this.notification.add(
                _t("A/B test: a copy of this mailing with the subject \"%s\" was made.", copy.name),
                { type: "success" });
        } finally {
            this.state.abBusy = false;
        }
    }

    /** "212 → 118 characters", "148 characters · 1 SMS" or "151 / 1,024", with whether it is over the limit. */
    countFor(text) {
        const after = countChars(text);
        if (this.kind === "sms") {
            const chars = text.length + (text.match(/\n/g) || []).length;
            const parts = countSMS(chars, extractSmsEncoding(text));
            return { label: _t("%(chars)s characters · %(parts)s SMS", { chars: after, parts }), over: parts > 1 };
        }
        if (this.kind === "messaging" && this.record.data.char_limit) {
            const limit = this.record.data.char_limit;
            return { label: `${after.toLocaleString()} / ${limit.toLocaleString()}`, over: after > limit };
        }
        const limit = this.record.data.composer_ui?.text?.limit || 0;
        const before = countChars(this.state.lastRequest?.original || "");
        return { label: _t("%(before)s → %(after)s characters", { before, after }), over: !!limit && after > limit };
    }
}

export const writingTools = {
    component: WritingTools,
    extractProps: ({ attrs }) => ({ field: attrs.field, compact: !!attrs.compact }),
};

registry.category("view_widgets").add("mi_writing_tools", writingTools);
