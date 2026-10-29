import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

import { Component, onWillStart, onWillUnmount, proxy, signal, useProps } from "@odoo/owl";

export const ATTACHMENT_LIMIT = 5;
export const ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024;
export const ACCEPTED_FILES = ".pdf,.txt,.md,.csv";
const AGENT_STORAGE_KEY = "ai_home.agent";
const REFRESH_MS = 60000;
const POLL_MS = 2000;
const POLL_LIMIT = 90;
const FINISHED = ["completed", "failed", "cancelled", "discarded", "uncertain"];

export const CATEGORIES = [
    ["all", _t("All")],
    ["approval", _t("Approvals")],
    ["conversation", _t("Conversations")],
    ["workflow", _t("Workflows")],
    ["ai", _t("AI agents")],
    ["activity", _t("Activities")],
    ["sales", _t("Sales")],
];
export const CATEGORY_LETTERS = {
    approval: "AP",
    conversation: "OC",
    workflow: "WF",
    ai: "AI",
    activity: "AC",
    sales: "SO",
};

/** Filter chips: "All" and every category that has rows, with counts. */
export function categoryTabs(items) {
    return CATEGORIES.map(([key, label]) => ({
        key,
        label,
        count: key === "all" ? items.length : items.filter((item) => item.category === key).length,
    })).filter((tab) => tab.key === "all" || tab.count);
}

/** Mine: my own; My team: mine and my team's; Everything: all. */
export function feedForScope(items, scope) {
    if (scope === "mine") {
        return items.filter((item) => item.scope === "mine");
    }
    if (scope === "team") {
        return items.filter((item) => item.scope !== "all");
    }
    return items;
}

export function greetingFor(hour) {
    if (hour < 12) {
        return _t("Good morning");
    }
    return hour < 18 ? _t("Good afternoon") : _t("Good evening");
}

function readAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new browser.FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

export class WorkDashboard extends Component {
    static template = "ai_home.WorkDashboard";
    props = useProps();
    fileInputRef = signal.ref();
    promptRef = signal.ref();

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            firstName: "",
            roleLabel: "",
            summary: "",
            live: [],
            attention: [],
            feed: [],
            day: [],
            recent: [],
            quickActions: [],
            agents: [],
            prompts: [],
            canManageAgents: false,
            category: "all",
            scope: "all",
            busy: "",
            prompt: "",
            agentId: "",
            showAgentMenu: false,
            attachments: [],
            uploading: false,
            chat: null,
        });

        onWillStart(async () => {
            await this.load();
            this.state.agentId = this.initialAgentId();
        });
        // "Right now" updates by itself.
        this.refreshTimer = browser.setInterval(() => this.load(), REFRESH_MS);
        onWillUnmount(() => {
            browser.clearInterval(this.refreshTimer);
            browser.clearTimeout(this.pollTimer);
        });
    }

    async load() {
        const data = await this.orm.call("ai.home.item", "get_home_data", []);
        Object.assign(this.state, data);
        if (!this.categories.some((tab) => tab.key === this.state.category)) {
            this.state.category = "all";
        }
    }

    /** The agent chosen last time in this browser, or the first one available. */
    initialAgentId() {
        let stored = "";
        try {
            stored = browser.localStorage.getItem(AGENT_STORAGE_KEY) || "";
        } catch {
            stored = "";
        }
        if (this.state.agents.some((agent) => String(agent.id) === stored)) {
            return stored;
        }
        return this.state.agents.length ? String(this.state.agents[0].id) : "";
    }

    // ------------------------------------------------------------------
    // Page
    // ------------------------------------------------------------------

    get greeting() {
        return greetingFor(luxon.DateTime.local().hour);
    }

    get dateLine() {
        return [luxon.DateTime.local().toFormat("cccc, d LLLL"), this.state.roleLabel, this.state.summary]
            .filter(Boolean)
            .join(" · ");
    }

    get aiAvailable() {
        return this.state.agents.length > 0;
    }

    get categories() {
        return categoryTabs(this.state.attention);
    }

    get attentionItems() {
        const category = this.state.category;
        return category === "all"
            ? this.state.attention
            : this.state.attention.filter((item) => item.category === category);
    }

    get scopes() {
        return [
            { key: "mine", label: _t("Mine") },
            { key: "team", label: _t("My team") },
            { key: "all", label: _t("Everything") },
        ];
    }

    get feedItems() {
        return feedForScope(this.state.feed, this.state.scope).slice(0, 6);
    }

    letters(item) {
        return CATEGORY_LETTERS[item.category] || "AC";
    }

    formatTime(value) {
        if (!value) {
            return "";
        }
        const when = deserializeDateTime(value);
        return when.hasSame(luxon.DateTime.local(), "day")
            ? when.toLocaleString(luxon.DateTime.TIME_24_SIMPLE)
            : formatDateTime(when, { format: "MMM d" });
    }

    openRecord(model, resId) {
        if (!model || !resId) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openTile(tile) {
        if (tile.action) {
            return this.action.doAction(tile.action);
        }
    }

    openItem(item) {
        if (item.openAction) {
            return this.action.doAction(item.openAction);
        }
        return this.openRecord(item.openModel || item.model, item.openId || item.resId);
    }

    async press(item, button) {
        if (button.open) {
            return this.openItem(item);
        }
        this.state.busy = item.key;
        try {
            const result = await this.orm.call("ai.home.item", "run_home_action", [
                item.model,
                item.resId,
                button.method,
            ]);
            if (result && result.type) {
                await this.action.doAction(result);
            }
        } finally {
            this.state.busy = "";
        }
        await this.load();
    }

    openActivities() {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: _t("My activities"),
            res_model: "mail.activity",
            domain: [["user_id", "=", user.userId]],
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
    }

    openFeed() {
        return this.action.doAction("mail.action_discuss");
    }

    openCalendar() {
        return this.action.doAction("calendar.action_calendar_event");
    }

    quickCreate(quick) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: quick.model,
            views: [[false, "form"]],
            target: "current",
            context: quick.context || {},
        });
    }

    // ------------------------------------------------------------------
    // Ask the assistant
    // ------------------------------------------------------------------

    get selectedAgent() {
        return this.state.agents.find((agent) => String(agent.id) === this.state.agentId) || null;
    }

    get aiName() {
        return this.selectedAgent?.name || _t("Assistant");
    }

    isSelected(agent) {
        return String(agent.id) === this.state.agentId;
    }

    selectAgent(agent) {
        this.state.agentId = String(agent.id);
        this.state.showAgentMenu = false;
        try {
            browser.localStorage.setItem(AGENT_STORAGE_KEY, this.state.agentId);
        } catch {
            // Remembering the choice is a convenience only.
        }
    }

    openAgents() {
        this.state.showAgentMenu = false;
        return this.action.doAction("ai_agent.action_agents");
    }

    chooseFiles() {
        this.fileInputRef()?.click();
    }

    async onFilesSelected(event) {
        const files = [...(event.target.files || [])];
        event.target.value = "";
        await this.addFiles(files);
    }

    /**
     * Upload chosen files as the user's own attachments. They go with the
     * question, so the agent reads them with the requester's permissions.
     */
    async addFiles(files) {
        const room = ATTACHMENT_LIMIT - this.state.attachments.length;
        if (files.length > room) {
            this.notification.add(_t("Attach at most %s files to one question.", ATTACHMENT_LIMIT), {
                type: "warning",
            });
        }
        const accepted = ACCEPTED_FILES.split(",");
        this.state.uploading = true;
        try {
            for (const file of files.slice(0, Math.max(0, room))) {
                const name = file.name || "file";
                if (!accepted.some((suffix) => name.toLowerCase().endsWith(suffix))) {
                    this.notification.add(_t("%s: attach PDF, text, Markdown or CSV files.", name), {
                        type: "warning",
                    });
                    continue;
                }
                if (file.size > ATTACHMENT_MAX_BYTES) {
                    this.notification.add(_t("%s is larger than 5 MB.", name), { type: "warning" });
                    continue;
                }
                const datas = await readAsBase64(file);
                const [id] = await this.orm.create("ir.attachment", [
                    { name, datas, res_model: false, res_id: 0 },
                ]);
                this.state.attachments.push({ id, name });
            }
        } finally {
            this.state.uploading = false;
        }
    }

    removeAttachment(file) {
        this.state.attachments = this.state.attachments.filter((current) => current.id !== file.id);
        this.orm.unlink("ir.attachment", [file.id]).catch(() => {});
    }

    get canSend() {
        return Boolean(this.state.prompt.trim() && this.selectedAgent && !this.state.chat?.waiting);
    }

    onPromptKeydown(event) {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            this.send();
        }
    }

    askSuggestion(text) {
        this.state.prompt = text;
        return this.send();
    }

    async send() {
        if (!this.canSend) {
            return;
        }
        const question = this.state.prompt.trim();
        const conversationId = this.state.chat?.conversationId || false;
        this.state.chat = { question, answer: "", error: "", waiting: true, conversationId };
        const { runId, conversationId: newConversation } = await this.orm.call("ai.home.item", "ask_ai", [
            Number(this.state.agentId),
            question,
            this.state.attachments.map((file) => file.id),
            conversationId,
        ]);
        this.state.prompt = "";
        this.state.attachments = [];
        this.state.chat.conversationId = newConversation;
        this.poll(runId, 0);
    }

    async poll(runId, round) {
        const result = await this.orm.call("ai.home.item", "get_ai_answer", [runId]);
        const chat = this.state.chat;
        if (!chat) {
            return;
        }
        if (FINISHED.includes(result.state)) {
            chat.waiting = false;
            chat.answer = result.answer;
            chat.error =
                result.state === "completed"
                    ? ""
                    : result.error || _t("The assistant could not answer. Open the conversation for details.");
            return;
        }
        if (round >= POLL_LIMIT) {
            chat.waiting = false;
            chat.error = _t("The answer is taking longer than usual. Open the conversation to follow it.");
            return;
        }
        this.pollTimer = browser.setTimeout(() => this.poll(runId, round + 1), POLL_MS);
    }

    closeChat() {
        browser.clearTimeout(this.pollTimer);
        this.state.chat = null;
    }

    openConversation() {
        return this.openRecord("ai.agent.conversation", this.state.chat?.conversationId);
    }
}

registry.category("actions").add("ai_home.dashboard", WorkDashboard);
