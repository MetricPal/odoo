import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    proxy,
    signal,
    useProps,
} from "@odoo/owl";

export const MY_WORK_MIN_FIT = 4;
export const ATTACHMENT_LIMIT = 5;
export const ATTACHMENT_MAX_BYTES = 5 * 1024 * 1024;
export const ACCEPTED_FILES = ".pdf,.txt,.md,.csv";
const AGENT_STORAGE_KEY = "ai_home.agent";
const MY_WORK_ROW_ESTIMATE = 56;
const ATTENTION_VISIBLE_LIMIT = 3;
export const AUTOMATION_STATUSES = ["active", "paused", "draft", "failed"];

export function splitDashboardItems(items) {
    return {
        attention: items.filter((item) => item.section === "attention"),
        automations: items.filter((item) => item.section === "automation"),
        recent: items.filter((item) => item.section === "recent"),
    };
}

/**
 * Group "My Work" items by day: Today, Yesterday, This week, Earlier.
 * `now` is injectable for tests.
 */
export function groupWorkByDay(items, now = luxon.DateTime.local()) {
    const startOfToday = now.startOf("day");
    const buckets = [
        { key: "today", label: _t("Today"), from: startOfToday },
        { key: "yesterday", label: _t("Yesterday"), from: startOfToday.minus({ days: 1 }) },
        { key: "week", label: _t("This week"), from: startOfToday.minus({ days: 7 }) },
        { key: "earlier", label: _t("Earlier"), from: null },
    ].map((bucket) => ({ ...bucket, items: [] }));
    for (const item of items) {
        const when = item.occurred ? deserializeDateTime(item.occurred) : null;
        const bucket =
            buckets.find((candidate) => candidate.from && when && when >= candidate.from) ||
            buckets[buckets.length - 1];
        bucket.items.push(item);
    }
    return buckets.filter((bucket) => bucket.items.length);
}

export function filterAutomations(items, status) {
    return status === "all" ? items : items.filter((item) => item.status === status);
}

/**
 * How many "My Work" rows to render: everything when it fits the visible
 * height, otherwise twice what fits so the column can scroll one more screen.
 */
export function myWorkVisibleCount(total, fit) {
    const capacity = Math.max(MY_WORK_MIN_FIT, fit || 0);
    return total <= capacity ? total : Math.min(total, capacity * 2);
}

const SECTION_ROW_REM = 3.75;
const SECTION_HEAD_REM = { automations: 5.75, runs: 3.25, recent: 3.25 };

export function rightSectionStyle(kind, rows) {
    const head = SECTION_HEAD_REM[kind] || 3.25;
    const weight = Math.max(1, Math.min(rows, 5));
    const max = head + Math.max(rows, 1) * SECTION_ROW_REM + 0.25;
    const min = Math.min(max, head + 1.5 * SECTION_ROW_REM);
    return `--o-rows: ${weight}; --o-head: ${head}rem; --o-max: ${max}rem; --o-min: ${min}rem;`;
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
    myWorkRef = signal.ref();
    fileInputRef = signal.ref();

    setup() {
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({
            items: [],
            attention: [],
            automations: [],
            runs: [],
            myWork: [],
            myWorkFit: 0,
            automationFilter: "all",
            mode: "manual",
            listening: false,
            showToolMenu: false,
            showAgentMenu: false,
            prompt: "",
            agents: [],
            agentId: "",
            canManageAgents: false,
            attachments: [],
            uploading: false,
            showAllAttention: false,
        });

        onWillStart(async () => {
            const data = await this.orm.call("ai.home.item", "get_home_data", []);
            this.state.items = data.items.map((item) => ({
                ...item,
                key: item.key || `item-${item.id}`,
                status: item.status || "active",
            }));
            this.state.attention = data.attention;
            this.state.automations = data.automations;
            this.state.runs = data.runs || [];
            this.state.myWork = data.myWork;
            this.state.agents = data.agents || [];
            this.state.canManageAgents = Boolean(data.canManageAgents);
            this.state.agentId = this.initialAgentId();
        });

        onMounted(() => {
            this.measureMyWork();
            if (browser.ResizeObserver && this.myWorkRef()) {
                this.resizeObserver = new browser.ResizeObserver(() => this.measureMyWork());
                this.resizeObserver.observe(this.myWorkRef());
            }
        });
        onWillUnmount(() => this.resizeObserver?.disconnect());
    }

    /** The agent chosen last time in this browser, or the only one available. */
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
        return this.state.agents.length === 1 ? String(this.state.agents[0].id) : "";
    }

    /**
     * Count the My Work rows that fit the visible height: the column itself
     * when it scrolls (tablet and desktop), otherwise the window (phone).
     */
    measureMyWork() {
        const list = this.myWorkRef();
        if (!list) {
            return;
        }
        const scrolls = browser.getComputedStyle(list).overflowY !== "visible";
        // Phone: the page scrolls, so the window minus the list's offset is visible.
        const height = scrolls ? list.clientHeight : browser.innerHeight - 48;
        const row = list.querySelector(".o_ai_home_mywork_item")?.offsetHeight || MY_WORK_ROW_ESTIMATE;
        // Day headings take roughly a sixth of a row each.
        const fit = Math.floor(height / (row * 1.15));
        if (fit !== this.state.myWorkFit) {
            this.state.myWorkFit = fit;
        }
    }

    get sections() {
        return splitDashboardItems(this.state.items);
    }

    get attentionAll() {
        return [...this.state.attention, ...this.sections.attention];
    }

    get attentionItems() {
        return this.state.showAllAttention
            ? this.attentionAll
            : this.attentionAll.slice(0, ATTENTION_VISIBLE_LIMIT);
    }

    get automationAll() {
        return [...this.state.automations, ...this.sections.automations];
    }

    get automationFilters() {
        const labels = {
            all: _t("All"),
            active: _t("Active"),
            paused: _t("Paused"),
            draft: _t("Draft"),
            failed: _t("Needs attention"),
        };
        return ["all", ...AUTOMATION_STATUSES]
            .map((value) => ({
                value,
                label: labels[value],
                count: filterAutomations(this.automationAll, value).length,
            }))
            .filter((filter) => filter.value === "all" || filter.count);
    }

    get automationItems() {
        return filterAutomations(this.automationAll, this.state.automationFilter);
    }

    get myWorkGroups() {
        const count = myWorkVisibleCount(this.state.myWork.length, this.state.myWorkFit);
        return groupWorkByDay(this.state.myWork.slice(0, count));
    }

    get canSend() {
        const agentId = Number(this.state.agentId);
        return Boolean(
            this.state.prompt.trim() && this.state.agents.some((agent) => agent.id === agentId)
        );
    }

    get speechSupported() {
        return Boolean(browser.SpeechRecognition || browser.webkitSpeechRecognition);
    }

    get recentItems() {
        return this.sections.recent;
    }

    /**
     * Height share of a right-column section (tablet and desktop): its title
     * always fits, the remaining height is shared by rows (capped so one long
     * list cannot crowd out the others), and no section grows past its rows.
     */
    sectionStyle(kind, rows) {
        return rightSectionStyle(kind, rows);
    }

    get acceptedFiles() {
        return ACCEPTED_FILES;
    }

    get selectedAgent() {
        return this.state.agents.find((agent) => this.isSelectedAgent(agent)) || null;
    }

    get agentLabel() {
        if (this.selectedAgent) {
            return this.selectedAgent.name;
        }
        return this.state.agents.length ? _t("Select agent") : _t("No active agent");
    }

    isSelectedAgent(agent) {
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
        this.state.showToolMenu = false;
        this.fileInputRef()?.click();
    }

    async onFilesSelected(event) {
        const files = [...(event.target.files || [])];
        event.target.value = "";
        await this.addFiles(files);
    }

    /**
     * Upload chosen files as the user's own attachments. They are linked to
     * the question when it is sent, so the agent reads them with the
     * requester's permissions.
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

    async openDashboardItem(item) {
        this.notification.add(item.subtitle || _t("Dashboard item opened."), {
            title: item.name,
            type: item.tone === "danger" ? "warning" : "info",
        });
        if (item.section === "recent") {
            const markedSeen = await this.orm.call(
                "ai.home.item",
                "mark_recent_seen",
                [item.id]
            );
            if (markedSeen) {
                this.state.items = this.state.items.filter((current) => current.id !== item.id);
            }
        }
    }

    openItem(item) {
        if (item.action) {
            return this.action.doAction({
                type: "ir.actions.act_window",
                res_model: item.action.res_model,
                res_id: item.action.res_id,
                views: [[false, "form"]],
                target: "current",
            });
        }
        return this.openDashboardItem(item);
    }

    formatTime(value) {
        if (!value) {
            return "";
        }
        const when = deserializeDateTime(value);
        return when.hasSame(luxon.DateTime.local(), "day")
            ? when.toLocaleString(luxon.DateTime.TIME_SIMPLE)
            : formatDateTime(when, { format: "MMM d" });
    }

    statusLabel(status) {
        return (
            {
                active: _t("Active"),
                paused: _t("Paused"),
                draft: _t("Draft"),
                failed: _t("Needs attention"),
            }[status] || ""
        );
    }

    prepareApproval() {
        this.state.showToolMenu = false;
        this.state.prompt = _t("Prepare an approval request for ");
        browser.document?.getElementById("ai_home_prompt")?.focus();
    }

    onPromptKeydown(event) {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            this.sendPrompt();
        }
    }

    toggleDictation() {
        if (this.state.listening) {
            this.recognition?.stop();
            return;
        }
        const Recognition = browser.SpeechRecognition || browser.webkitSpeechRecognition;
        if (!Recognition) {
            return;
        }
        // Dictation only fills the text box; nothing is sent until the user does.
        const recognition = new Recognition();
        recognition.lang = user.lang?.replace("_", "-") || "en-US";
        recognition.interimResults = false;
        recognition.onresult = (event) => {
            const text = Array.from(event.results)
                .map((result) => result[0].transcript)
                .join(" ");
            this.state.prompt = [this.state.prompt.trim(), text].filter(Boolean).join(" ");
        };
        recognition.onend = () => {
            this.state.listening = false;
        };
        recognition.onerror = () => {
            this.state.listening = false;
        };
        this.recognition = recognition;
        this.state.listening = true;
        recognition.start();
    }

    async sendPrompt() {
        if (!this.canSend) {
            return;
        }
        if (this.state.mode !== "auto") {
            return this.reviewRequest();
        }
        // Auto: the user's Send authorizes one inference request, exactly as
        // the dialog's Send button does. It never changes records.
        const [askId] = await this.orm.create("ai.agent.ask", [
            {
                agent_id: Number(this.state.agentId),
                prompt: this.state.prompt.trim(),
                attachment_ids: [[6, 0, this.state.attachments.map((file) => file.id)]],
            },
        ]);
        const action = await this.orm.call("ai.agent.ask", "action_send", [[askId]]);
        this.state.prompt = "";
        this.state.attachments = [];
        return this.action.doAction(action);
    }

    reviewRequest() {
        const agentId = Number(this.state.agentId);
        if (!this.canSend) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "ai.agent.ask",
            views: [[false, "form"]],
            target: "new",
            name: _t("Ask me"),
            context: {
                default_agent_id: agentId,
                default_prompt: this.state.prompt.trim(),
                default_attachment_ids: this.state.attachments.map((file) => file.id),
            },
        });
    }

}

registry.category("actions").add("ai_home.dashboard", WorkDashboard);
