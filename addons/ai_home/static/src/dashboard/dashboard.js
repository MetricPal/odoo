import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

import { AssistantsDialog } from "./assistants_dialog";

import { Component, onMounted, onWillStart, onWillUnmount, proxy, signal, useProps } from "@odoo/owl";

export const ATTACHMENT_LIMIT = 5;
export const ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024;
export const ACCEPTED_FILES = ".pdf,.txt,.md,.csv";
const AGENT_STORAGE_KEY = "ai_home.agent";
/** The conversation shown on Home, so it is there again after the page is reloaded. */
const CONVERSATION_STORAGE_KEY = "ai_home.conversation";
const REFRESH_MS = 60000;
const POLL_MS = 2000;
const POLL_LIMIT = 90;
const FINISHED = ["completed", "failed", "cancelled", "discarded", "uncertain"];

export const PLAN_SECTIONS = [
    ["late", _t("Late")],
    ["today", _t("Today")],
    ["tomorrow", _t("Tomorrow")],
    ["week", _t("This week")],
    ["later", _t("Later")],
];
const RING_RADIUS = 34;
export const RING_LENGTH = 2 * Math.PI * RING_RADIUS;

const INSIGHT_RANK = { bad: 1, warn: 3, info: 4, good: 5 };

/**
 * The one middle list: decisions and insights together, most urgent first. Overdue decisions, then red insights,
 * then the other decisions, orange, grey (incomplete information) and green (going well) insights.
 */
export function streamList(attention, insights) {
    const rank = (item) =>
        item.kind === "insight" ? INSIGHT_RANK[item.tone] ?? 4 : item.overdue ? 0 : 2;
    return [...attention, ...insights]
        .map((item, index) => ({ item, index, rank: rank(item) }))
        .sort((a, b) => a.rank - b.rank || a.index - b.index)
        .map(({ item }) => item);
}

/** App chips for My plan: "All", then each app with items, most items first. */
export function planApps(items) {
    const counts = new Map();
    for (const item of items) {
        counts.set(item.app, (counts.get(item.app) || 0) + 1);
    }
    const apps = [...counts.entries()]
        .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
        .map(([app, count]) => ({ key: app, label: app, count }));
    return [{ key: "all", label: _t("All"), count: items.length }, ...apps];
}

/** My plan in sections (Late, Today, Tomorrow, This week, Later), for one app or all. */
export function planSections(items, app = "all") {
    const shown = app === "all" ? items : items.filter((item) => item.app === app);
    return PLAN_SECTIONS.map(([key, label]) => ({
        key,
        label,
        items: shown.filter((item) => item.section === key),
    })).filter((section) => section.items.length);
}

/** What others did. For me: Odoo notified the user; My team: done by team members; Everything: all. */
export function feedForScope(items, scope) {
    if (scope === "forMe") {
        return items.filter((item) => item.forMe);
    }
    if (scope === "team") {
        return items.filter((item) => item.team);
    }
    return items;
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
    askRef = signal.ref();
    streamRef = signal.ref();

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.state = proxy({
            today: { done: 0, late: 0, todo: 0, total: 0, label: "" },
            week: [],
            plan: [],
            waiting: [],
            team: [],
            attention: [],
            attentionGroups: [],
            insights: [],
            systemSummary: false,
            feed: [],
            recent: [],
            agents: [],
            pausedAgents: [],
            aiProblem: false,
            prompts: [],
            canManageAgents: false,
            planApp: "all",
            openSections: { late: true, today: true, tomorrow: false, week: false, later: false },
            snoozeKey: "",
            recentOpen: false,
            waitingOpen: null,
            scope: "forMe",
            busy: "",
            prompt: "",
            agentId: "",
            canRoute: false,
            showAgentMenu: false,
            showSuggestMenu: false,
            showChangeMenu: false,
            attachments: [],
            uploading: false,
            chat: null,
            chatTurns: [],
            now: Date.now(),
        });

        onWillStart(async () => {
            await this.load();
            this.state.agentId = this.initialAgentId();
        });
        // Home updates by itself.
        this.refreshTimer = browser.setInterval(() => this.load(), REFRESH_MS);
        // The time waited for an answer counts up every second, only while one is awaited.
        this.waitTimer = browser.setInterval(() => {
            if (this.state.chat?.waiting) {
                this.state.now = Date.now();
            }
        }, 1000);
        // The middle list runs behind the assistant to the bottom of the page; its bottom padding is the assistant's
        // height (--home-ask-height), so the last item can always scroll clear of it.
        onMounted(() => {
            const ask = this.askRef();
            if (ask) {
                this.askObserver = new ResizeObserver(() =>
                    ask.parentElement.style.setProperty("--home-ask-height", `${ask.offsetHeight}px`)
                );
                this.askObserver.observe(ask);
            }
            this.restoreConversation();
            window.addEventListener("click", this.closeMenusOutside, true);
            window.addEventListener("keydown", this.closeMenusOnEscape);
        });
        onWillUnmount(() => {
            window.removeEventListener("click", this.closeMenusOutside, true);
            window.removeEventListener("keydown", this.closeMenusOnEscape);
            browser.clearInterval(this.refreshTimer);
            browser.clearInterval(this.waitTimer);
            browser.clearTimeout(this.pollTimer);
            this.askObserver?.disconnect();
        });
    }

    // The assistant menus (the picker under the Ask box, "Change" on an answer) close on a click anywhere outside
    // them and on Escape, as Odoo's own dropdowns do.
    closeMenusOutside = (ev) => {
        if (this.state.showAgentMenu && !ev.target.closest?.(".o_ai_home_agent_picker")) {
            this.state.showAgentMenu = false;
        }
        if (this.state.showSuggestMenu && !ev.target.closest?.(".o_ai_home_suggest_picker")) {
            this.state.showSuggestMenu = false;
        }
        if (this.state.showChangeMenu && !ev.target.closest?.(".o_ai_home_chat_change")) {
            this.state.showChangeMenu = false;
        }
    };

    closeMenusOnEscape = (ev) => {
        if (ev.key === "Escape") {
            this.state.showAgentMenu = false;
            this.state.showSuggestMenu = false;
            this.state.showChangeMenu = false;
        }
    };

    async load() {
        const data = await this.orm.call("ai.home.item", "get_home_data", []);
        Object.assign(this.state, data);
        if (!this.planAppTabs.some((tab) => tab.key === this.state.planApp)) {
            this.state.planApp = "all";
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
        // "Choose for me" is the default when it is offered (ADR 0015, approved board 19).
        if (this.state.canRoute) {
            return "auto";
        }
        return this.state.agents.length ? String(this.state.agents[0].id) : "";
    }

    // ------------------------------------------------------------------
    // Page
    // ------------------------------------------------------------------

    get aiAvailable() {
        return this.state.agents.length > 0;
    }

    get streamItems() {
        return streamList(this.state.attention, this.state.insights);
    }

    get planAppTabs() {
        return planApps(this.state.plan);
    }

    get sections() {
        return planSections(this.state.plan, this.state.planApp);
    }

    isOpen(section) {
        return Boolean(this.state.openSections[section.key]);
    }

    toggleSection(section) {
        this.state.openSections[section.key] = !this.state.openSections[section.key];
    }

    /** Stroke of the "done today" ring: done out of done + due today + late. */
    get ringDash() {
        const { done, total } = this.state.today;
        const filled = total ? (RING_LENGTH * done) / total : 0;
        return `${filled.toFixed(1)} ${RING_LENGTH.toFixed(1)}`;
    }

    weekBarHeight(day) {
        const busiest = Math.max(1, ...this.state.week.map((entry) => entry.count));
        return `${Math.max(4, Math.round((100 * day.count) / busiest))}%`;
    }

    weekBarLabel(day) {
        return day.count === 1
            ? _t("%s: 1 item", day.longLabel)
            : _t("%(day)s: %(count)s items", { day: day.longLabel, count: day.count });
    }

    /** Waiting on others is open, except for managers (Team load covers their people) until they open it. */
    get waitingOpen() {
        return this.state.waitingOpen ?? !this.state.team.length;
    }

    get recentSummary() {
        return this.state.recent
            .slice(0, 2)
            .map((record) => record.name)
            .join(", ");
    }

    get scopes() {
        return [
            { key: "forMe", label: _t("For me") },
            { key: "team", label: _t("My team") },
            { key: "all", label: _t("Everything") },
        ];
    }

    get feedItems() {
        return feedForScope(this.state.feed, this.state.scope);
    }

    letters(item) {
        return item.badge || "AC";
    }

    /** Today, Yesterday, or the date (Oct 29). */
    humanDate(value) {
        if (!value) {
            return "";
        }
        const when = deserializeDateTime(value);
        const now = luxon.DateTime.local();
        if (when.hasSame(now, "day")) {
            return _t("Today");
        }
        if (when.hasSame(now.minus({ days: 1 }), "day")) {
            return _t("Yesterday");
        }
        return formatDateTime(when, { format: "MMM d" });
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

    async openInsight(row) {
        const action = await this.orm.call("ai.home.insight", "action_open", [[row.insightId]]);
        return this.action.doAction(action);
    }

    toggleSnooze(item) {
        this.state.snoozeKey = this.state.snoozeKey === item.key ? "" : item.key;
    }

    snooze(item, method) {
        this.state.snoozeKey = "";
        return this.press(item, { method });
    }

    join(item) {
        if (item.joinUrl) {
            browser.open(item.joinUrl, "_blank");
        }
    }

    /** Open the list behind a Today count: all (the ring), late, todo or done. */
    openToday(key) {
        return this.action.doAction(this.state.today.actions[key]);
    }

    /** Open the activities due on a day of Next 7 days. */
    openDay(day) {
        return this.action.doAction(day.action);
    }

    openPerson(row) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: row.name,
            res_model: "mail.activity",
            domain: [["user_id", "=", row.userId]],
            views: [
                [false, "list"],
                [false, "form"],
            ],
            target: "current",
        });
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

    openSystemOverview() {
        return this.action.doAction("ai_home.action_system_overview");
    }

    get systemLine() {
        const summary = this.state.systemSummary;
        if (!summary) {
            return "";
        }
        const parts = [
            _t("%s active users today", summary.users),
            _t("%s transactions", summary.transactions),
        ];
        if (summary.failing) {
            parts.push(summary.failing === 1 ? _t("1 check failing") : _t("%s checks failing", summary.failing));
        }
        return parts.join(" · ");
    }

    openInbox() {
        return this.action.doAction("mail.action_discuss");
    }

    // ------------------------------------------------------------------
    // Ask the assistant
    // ------------------------------------------------------------------

    /** "Choose for me" in the assistant picker (ADR 0015). */
    get autoAgent() {
        return { id: "auto", name: _t("Choose for me") };
    }

    get selectedAgent() {
        if (this.state.agentId === "auto") {
            return this.state.canRoute ? this.autoAgent : null;
        }
        return this.state.agents.find((agent) => String(agent.id) === this.state.agentId) || null;
    }

    get aiName() {
        if (this.state.agentId === "auto" && this.state.canRoute) {
            return _t("an assistant");
        }
        return this.selectedAgent?.name || (this.aiAvailable ? _t("Assistant") : _t("No assistant"));
    }

    /** The assistant picker's label: "Choose for me" or the chosen assistant. */
    get pickerLabel() {
        if (!this.aiAvailable && this.state.aiProblem) {
            return _t("Assistant unavailable");
        }
        return this.state.agentId === "auto" && this.state.canRoute ? this.autoAgent.name : this.aiName;
    }

    /** The Ask box's hint: how to ask, why the assistant cannot answer right now, or how to get an assistant. */
    get promptPlaceholder() {
        if (this.aiAvailable) {
            return _t("How can I help you today? Ask a question or ask %s to do something", this.aiName);
        }
        return (
            this.state.aiProblem?.text ||
            _t("No assistant is available to you yet. Ask your admin to set one up in AI Agents.")
        );
    }

    /** The other assistants the same question can be sent to (Change ▾). */
    get changeAgents() {
        const current = this.state.chat?.answeredById;
        return this.state.agents.filter((agent) => agent.id !== current);
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

    /** Every assistant in the picker: the ones that answer, then the paused ones (greyed out). */
    get pickerAgents() {
        return [...this.state.agents, ...this.state.pausedAgents.map((agent) => ({ ...agent, paused: true }))];
    }

    /** What each assistant can do (approved mock 2026-11-08): Ask chooses it in the assistant box. */
    async openAssistants() {
        this.state.showAgentMenu = false;
        const assistants = await this.orm.call("ai.home.item", "get_assistant_details", []);
        this.dialog.add(AssistantsDialog, {
            assistants,
            selectedId: this.state.agentId,
            canManage: this.state.canManageAgents,
            onAsk: (assistant) => {
                const agent = this.state.agents.find((item) => item.id === assistant.id);
                if (agent) {
                    this.selectAgent(agent);
                    this.promptRef()?.focus();
                }
            },
            onManage: () => this.openAgents(),
        });
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
        this.state.showSuggestMenu = false;
        this.state.prompt = text;
        return this.send();
    }

    async send() {
        if (!this.canSend) {
            return;
        }
        const question = this.state.prompt.trim();
        const previous = this.state.chat;
        const conversationId = previous?.conversationId || false;
        // After "Choose for me", the next question in the same conversation goes to the assistant that answered.
        let agentId = this.state.agentId === "auto" ? previous?.answeredById || false : Number(this.state.agentId);
        if (this.state.agentId === "auto" && !conversationId) {
            agentId = false;
        }
        await this.ask(question, agentId, conversationId, {
            answeredBy: agentId && previous?.answeredById === agentId ? previous.answeredBy : "",
            answeredById: agentId && previous?.answeredById === agentId ? agentId : false,
            why: agentId && previous?.answeredById === agentId ? previous.why : "",
        });
    }

    async ask(question, agentId, conversationId, routed = {}) {
        this.state.showChangeMenu = false;
        // Every question and its answer stay on Home, under the last item of the middle list; `chat` is the newest.
        this.state.chatTurns.push({
            question, answer: "", error: "", did: "", waiting: true, conversationId, choosing: !agentId,
            startedAt: Date.now(),
            agentName: this.state.agents.find((agent) => agent.id === agentId)?.name || "",
            agentAvatar: this.state.agents.find((agent) => agent.id === agentId)?.avatarUrl || "",
            answeredBy: "", answeredById: false, why: "", ...routed,
        });
        this.state.chat = this.state.chatTurns.at(-1);
        this.state.now = Date.now();
        this.scrollToChat();
        let asked;
        try {
            asked = await this.orm.call("ai.home.item", "ask_ai", [
                agentId,
                question,
                this.state.attachments.map((file) => file.id),
                conversationId,
            ]);
        } catch (error) {
            // Refused before it started (for example the daily limit): say why where "Thinking…" was, no popup;
            // the question stays in the box (owner, 2026-11-13).
            if (!error.data?.message) {
                throw error;
            }
            Object.assign(this.state.chat, { waiting: false, choosing: false, error: error.data.message });
            this.scrollToChat();
            return;
        }
        const { runId, conversationId: newConversation } = asked;
        this.state.prompt = "";
        this.state.attachments = [];
        this.state.chat.conversationId = newConversation;
        this.rememberConversation(newConversation);
        this.poll(runId, 0);
    }

    /** Change ▾: the same question to another assistant, in a new conversation with it. */
    askAgain(agent) {
        const question = this.state.chat?.question;
        if (!question) {
            return;
        }
        browser.clearTimeout(this.pollTimer);
        return this.ask(question, agent.id, false, { answeredBy: agent.name, answeredById: agent.id, why: "" });
    }

    async poll(runId, round) {
        const result = await this.orm.call("ai.home.item", "get_ai_answer", [runId]);
        const chat = this.state.chat;
        if (!chat) {
            return;
        }
        chat.choosing = result.state === "choosing";
        if (result.answeredBy) {
            chat.answeredBy = result.answeredBy;
            chat.why = result.why;
        }
        if (result.answeredById) {
            chat.answeredById = result.answeredById;
        }
        if (result.conversationId) {
            chat.conversationId = result.conversationId;
            this.rememberConversation(result.conversationId);
        }
        if (result.agentName) {
            chat.agentName = result.agentName;
            chat.agentAvatar = result.agentAvatar || "";
        }
        if (FINISHED.includes(result.state)) {
            chat.waiting = false;
            chat.answer = result.answer;
            chat.did = result.did || "";
            chat.error =
                result.state === "completed"
                    ? ""
                    : result.error || _t("The assistant could not answer. Open the conversation for details.");
            chat.fixUrl = result.fixUrl || "";
            chat.fixLabel = result.fixLabel || "";
            this.scrollToChat();
            return;
        }
        if (round >= POLL_LIMIT) {
            chat.waiting = false;
            chat.error = _t("The answer is taking longer than usual. Open the conversation to follow it.");
            this.scrollToChat();
            return;
        }
        this.pollTimer = browser.setTimeout(() => this.poll(runId, round + 1), POLL_MS);
    }

    closeChat() {
        browser.clearTimeout(this.pollTimer);
        this.state.chat = null;
        this.state.chatTurns = [];
        this.rememberConversation(false);
    }

    /** The letter in front of an answer: the initial of the assistant that answers ("AI" until it is known). */
    turnInitial(turn) {
        const name = turn.agentName || turn.answeredBy;
        return name ? name.trim().charAt(0).toUpperCase() : _t("AI");
    }

    /**
     * While the assistant works on a question: what to say, by how long it has taken. The same steps and words as a
     * slow answer in the assistant's chat (10 s, 30 s), followed by the time waited.
     */
    waitingText(turn) {
        const seconds = Math.max(0, Math.floor((this.state.now - turn.startedAt) / 1000));
        if (seconds >= 30) {
            return _t("Still working on it; the AI service is slow right now.");
        }
        if (seconds >= 10) {
            return _t("This is taking a bit longer than usual…");
        }
        return turn.choosing ? _t("Choosing the right assistant…") : _t("Thinking…");
    }

    /** The time waited, as people say it: "8 s", "1 min 5 s". */
    waitedText(turn) {
        const seconds = Math.max(0, Math.floor((this.state.now - turn.startedAt) / 1000));
        return seconds >= 60 ? _t("%(minutes)s min %(seconds)s s", { minutes: Math.floor(seconds / 60), seconds: seconds % 60 }) : _t("%s s", seconds);
    }

    rememberConversation(conversationId) {
        try {
            if (conversationId) {
                browser.localStorage.setItem(CONVERSATION_STORAGE_KEY, String(conversationId));
            } else {
                browser.localStorage.removeItem(CONVERSATION_STORAGE_KEY);
            }
        } catch {
            // Keeping the conversation across a reload is a convenience only.
        }
    }

    /** After a reload: the conversation that was on Home is shown again, and a pending answer is followed. */
    async restoreConversation() {
        let conversationId;
        try {
            conversationId = Number(browser.localStorage.getItem(CONVERSATION_STORAGE_KEY));
        } catch {
            return;
        }
        if (!conversationId || this.state.chat) {
            return;
        }
        const turns = await this.orm.call("ai.home.item", "get_ai_conversation", [conversationId]);
        if (!turns.length || this.state.chat) {
            return;
        }
        for (const turn of turns) {
            const waiting = !FINISHED.includes(turn.state);
            this.state.chatTurns.push({
                question: turn.question, answer: turn.answer || "", did: turn.did || "", waiting,
                error: waiting || turn.state === "completed" ? "" : turn.error || "",
                fixUrl: turn.fixUrl || "", fixLabel: turn.fixLabel || "",
                conversationId: turn.conversationId || conversationId, choosing: turn.state === "choosing",
                startedAt: Date.now() - (turn.waited || 0) * 1000,
                agentName: turn.agentName || "", agentAvatar: turn.agentAvatar || "",
                answeredBy: turn.answeredBy || "",
                answeredById: turn.answeredById || false, why: turn.why || "",
            });
        }
        this.state.chat = this.state.chatTurns.at(-1);
        if (this.state.chat.waiting) {
            this.poll(turns.at(-1).runId, 0);
        }
        this.scrollToChat();
    }

    /** Brings the newest question and answer into view, at the bottom of the middle list, once they are drawn. */
    scrollToChat() {
        requestAnimationFrame(() =>
            requestAnimationFrame(() => {
                const list = this.streamRef();
                if (!list) {
                    return;
                }
                list.scrollTop = list.scrollHeight;
                if (list.scrollHeight <= list.clientHeight) {
                    // On a narrow screen the page scrolls, not the list.
                    list.querySelector(".o_ai_home_chat")?.scrollIntoView({ block: "end" });
                }
            })
        );
    }

    openConversation() {
        return this.openRecord("ai.agent.conversation", this.state.chat?.conversationId);
    }
}

registry.category("actions").add("ai_home.dashboard", WorkDashboard);
