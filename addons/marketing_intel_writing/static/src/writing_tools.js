import { Component, onMounted, onWillDestroy, onWillStart, onWillUnmount, proxy, signal, t, useProps } from "@odoo/owl";
import { GSM7_MAX_CHAR, UCS2_MAX_CHAR, countSMS, extractSmsEncoding } from "@sms/core/sms_char_counter_utils";
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
 * Writing tools on a marketing text (approved boards 8.1 to 8.4; one look everywhere, board 9.1 option A plus):
 * placed after the field inside its `.o_mi_text_box`, it draws over the field's box the ✦ (top-right, after Odoo's
 * own text icons) and the character count (bottom-right), and the assistant's suggestion right under the box with
 * Use / Try again / Discard. The text changes only on Use.
 */
export class WritingTools extends Component {
    static template = "marketing_intel_writing.WritingTools";
    static components = { Dropdown, DropdownItem };
    props = useProps({
        ...standardWidgetProps,
        field: t.string(),
    });

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = proxy({
            tools: null, suggestion: null, customOpen: false, customText: "", lastRequest: null, abBusy: false,
            boxHeight: 0, typed: null,
        });
        this.rootRef = signal.ref();
        onMounted(() => this.watchBox());
        onWillUnmount(() => this.unwatchBox());
        this.request = new SuggestionRequest(this.orm, (result) => this.onResult(result));
        onWillStart(async () => {
            this.state.tools = await this.orm.call("mi.writing", "get_tools",
                [this.props.record.resModel, this.props.field]);
        });
        onWillDestroy(() => this.request.cancel());
    }

    get record() { return this.props.record; }
    get tools() { return { available: false, tools: [], ...this.state.tools }; }
    get kind() { return this.tools.kind; }
    /** What is in the box now, typed or not yet saved to the record. */
    get text() { return this.state.typed ?? (this.record.data[this.props.field] || ""); }

    /** The field's element in the same box: its height places the corners, its input gives the live text. */
    watchBox() {
        const box = this.rootRef()?.closest(".o_mi_text_box");
        this.fieldEl = box?.querySelector(`.o_field_widget[name="${this.props.field}"]`);
        if (!this.fieldEl) {
            return;
        }
        this.input = this.fieldEl.querySelector("textarea, input");
        this.onInput = () => { this.state.typed = this.input.value; };
        this.input?.addEventListener("input", this.onInput);
        this.resizer = new ResizeObserver(() => { this.state.boxHeight = this.fieldEl.offsetHeight; });
        this.resizer.observe(this.fieldEl);
        this.state.boxHeight = this.fieldEl.offsetHeight;
    }
    unwatchBox() {
        this.input?.removeEventListener("input", this.onInput);
        this.resizer?.disconnect();
    }
    /**
     * The count in the box's bottom-right corner (Social's composer draws its own): "n / limit" where the channel
     * has a limit, else "n characters". `level` is "over" past the limit (red) and "long" past what a reader sees
     * whole (orange), with `title` saying why.
     */
    get boxCount() {
        if (this.kind === "social" || !this.kind) {
            return null;
        }
        const text = this.text;
        const chars = countChars(text);
        const fmt = (n) => n.toLocaleString();
        if (this.kind === "sms") {
            // One SMS holds 160 plain Latin characters, or 70 once the text needs Unicode (other scripts, emoji).
            const encoding = extractSmsEncoding(text);
            const perSms = encoding === "UNICODE" ? UCS2_MAX_CHAR : GSM7_MAX_CHAR;
            const parts = countSMS(text.length + (text.match(/\n/g) || []).length, encoding);
            return {
                label: _t("%(chars)s / %(limit)s · %(parts)s SMS", { chars: fmt(chars), limit: perSms, parts }),
                level: parts > 1 ? "over" : "",
                title: encoding === "UNICODE"
                    ? _t("This text needs Unicode, so one SMS holds 70 characters.")
                    : _t("One SMS holds 160 characters."),
            };
        }
        const limit = this.kind === "messaging" ? this.record.data.char_limit : this.tools.limit;
        if (!limit) {
            return { label: _t("%s characters", fmt(chars)), level: "", title: "" };
        }
        // A soft limit (email subject, preview text) is a recommended length: past it the text still sends but is
        // cut, so orange; a channel's limit (Messaging) is red.
        const soft = this.kind !== "messaging" && this.tools.soft;
        let level = "";
        let title = soft ? this.tools.limit_note || "" : "";
        if (chars > limit) {
            level = soft ? "long" : "over";
            title = title || _t("Longer than %s characters.", fmt(limit));
        }
        return { label: `${fmt(chars)} / ${fmt(limit)}`, level, title };
    }
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
        this.state.typed = null;
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
    extractProps: ({ attrs }) => ({ field: attrs.field }),
};

registry.category("view_widgets").add("mi_writing_tools", writingTools);
