import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { Layout } from "@web/search/layout";
import { useSubEnv } from "@web/owl2/utils";
import { getDefaultConfig } from "@web/views/view";
import { useSetupAction } from "@web/search/action_hook";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

export class Workflows extends Component {
    static template = "workflow_center.Workflows";
    static components = { Layout };
    props = useProps();
    setup() {
        useSubEnv({ config: { ...getDefaultConfig(), ...this.env.config } });
        useSetupAction();
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = proxy({
            page: this.constructor.initialPage || "home", category: "All", data: { templates: [], workflows: [], models: [] },
            workflow: null, selected: null, runFilter: "all", runs: [], run: null,
            description: "When a customer invoice is 7 days overdue, email the customer a reminder. If it is still unpaid 7 days later, create a call activity for the salesperson.",
            modelId: "", busy: false,
        });
        this.categories = ["All", "Reminders", "Data updates", "Create records", "Scheduled", "Integrations", "Approvals"];
        this.blocks = [
            { title: "Actions", items: [
                ["action", "object_write", "Update record", "edit"],
                ["action", "object_create", "Create record", "add"],
                ["action", "next_activity", "Schedule activity", "calendar_today"],
                ["action", "followers", "Add followers", "group"],
                ["action", "mail_post", "Email or Odoo message", "mail"],
                ["action", "chat", "Provider chat", "chat_bubble"],
                ["action", "webhook", "Call webhook", "link"],
                ["action", "code", "Python code", "code"],
            ] },
            { title: "Logic", items: [
                ["condition", "object_write", "Condition", "filter_alt"],
                ["branch", "object_write", "Branch", "account_tree"],
                ["wait", "object_write", "Wait", "schedule"],
                ["foreach", "object_write", "For each record", "autorenew"],
            ] },
            { title: "Optional", items: [["approval", "object_write", "Approval", "checklist"]] },
        ];
        onWillStart(async () => {
            await this.loadHome();
            if (this.state.page === "runs") await this.loadRuns();
        });
    }
    async loadHome() {
        this.state.data = await this.orm.call("workflow.definition", "home_data", []);
        if (!this.state.modelId && this.state.data.models.length) {
            this.state.modelId = String((this.state.data.models.find(m => m.model === 'account.move') || this.state.data.models.find(m => m.model === 'res.partner') || this.state.data.models[0]).id);
        }
    }
    get templates() {
        return this.state.data.templates.filter(t => this.state.category === "All" || t.category === this.state.category);
    }
    get selectedStep() {
        return this.state.workflow?.steps.find(s => s.id === this.state.selected);
    }
    get canvas() {
        const steps = this.state.workflow?.steps || [];
        const byId = new Map(steps.map(s => [s.id, s]));
        const next = s => s.end ? null : byId.get(s.next_id?.[0]) || steps.find(n => n.sequence > s.sequence);
        const seen = new Set();
        const reachable = (start, found = new Set()) => {
            if (!start || found.has(start.id)) return found;
            found.add(start.id);
            reachable(next(start), found);
            if (start.kind === "branch") reachable(byId.get(start.false_id?.[0]), found);
            return found;
        };
        const build = (start, stop = null, depth = 0) => {
            const nodes = [];
            let step = start;
            while (step && step.id !== stop?.id && !seen.has(step.id) && depth < 100) {
                seen.add(step.id);
                const node = { step, yes: [], no: [] };
                nodes.push(node);
                if (step.kind === "branch") {
                    const yes = next(step), no = byId.get(step.false_id?.[0]);
                    const yesIds = reachable(yes), noIds = reachable(no);
                    const common = steps.find(s => yesIds.has(s.id) && noIds.has(s.id) && !seen.has(s.id));
                    node.yes = build(yes, common || stop, depth + 1);
                    node.no = build(no, common || stop, depth + 1);
                    step = common;
                } else { step = next(step); }
            }
            return nodes;
        };
        const nodes = build(steps[0]);
        return { nodes, unused: steps.filter(s => !seen.has(s.id)) };
    }
    async openWorkflow(id) {
        this.state.workflow = await this.orm.call("workflow.definition", "builder_data", [[id]]);
        this.state.page = "builder";
        if (!this.state.workflow.steps.some(s => s.id === this.state.selected)) this.state.selected = null;
    }
    async fromTemplate(template) {
        if (this.state.busy) return;
        this.state.busy = true;
        try {
            const id = await this.orm.call("workflow.definition", "from_template", [template.key]);
            await this.openWorkflow(id);
        } finally { this.state.busy = false; }
    }
    newWorkflow() {
        this.dialog.add(FormViewDialog, {
            resModel: "workflow.definition", title: "New workflow",
            context: { default_model_id: Number(this.state.modelId), default_description: this.state.description },
            onRecordSaved: record => this.openWorkflow(record.resId),
        });
    }
    configureWorkflow() {
        const workflow = this.state.workflow;
        this.dialog.add(FormViewDialog, {
            resModel: "workflow.definition", resId: workflow.id, title: "When and which records",
            readonly: workflow.state === "active",
            onRecordSaved: () => this.openWorkflow(workflow.id),
        });
    }
    configureStep(step) {
        this.state.selected = step.id;
        this.dialog.add(FormViewDialog, {
            resModel: "workflow.step", resId: step.id, title: step.name,
            readonly: this.state.workflow.state === "active",
            onRecordSaved: () => this.openWorkflow(this.state.workflow.id),
        });
    }
    async addStep(item) {
        const id = await this.orm.call("workflow.definition", "add_step", [[this.state.workflow.id], item[0], item[1], this.state.selected || false]);
        await this.openWorkflow(this.state.workflow.id);
        this.state.selected = id;
        this.configureStep(this.selectedStep);
    }
    removeStep(step) {
        this.dialog.add(ConfirmationDialog, {
            title: "Remove step", body: "Remove this step from the draft? If another branch points here, update that branch first.",
            confirm: async () => {
                await this.orm.unlink("workflow.step", [step.id]);
                await this.openWorkflow(this.state.workflow.id);
            },
        });
    }
    async testRun() {
        const action = await this.orm.call("workflow.definition", "action_test_dialog", [[this.state.workflow.id]]);
        await this.action.doAction(action, { onClose: () => this.openWorkflow(this.state.workflow.id) });
    }
    activate() {
        this.dialog.add(ConfirmationDialog, {
            title: "Activate workflow",
            body: "Authorize this workflow's configured actions, trigger, record filter, execution user and company? Matching events will run automatically. The shared worker will resume waits and scheduled runs. You can pause the workflow at any time.",
            confirmLabel: "Activate",
            confirm: async () => {
                await this.orm.call("workflow.definition", "action_activate", [[this.state.workflow.id]]);
                await this.openWorkflow(this.state.workflow.id);
            },
        });
    }
    async pause() {
        await this.orm.call("workflow.definition", "action_pause", [[this.state.workflow.id]]);
        await this.openWorkflow(this.state.workflow.id);
    }
    async loadRuns() {
        const domain = this.state.runFilter === "all" ? [] : [["state", "=", this.state.runFilter]];
        this.state.runs = await this.orm.searchRead("workflow.run", domain,
            ["workflow_id", "name", "step_id", "state", "started_at", "is_test"], { limit: 200 });
        if (this.state.run) await this.openRun(this.state.run.id);
    }
    async filterRuns(filter) {
        this.state.runFilter = filter;
        this.state.run = null;
        await this.loadRuns();
    }
    async openRun(id) {
        const [run] = await this.orm.read("workflow.run", [id], [
            "workflow_id", "name", "step_id", "step_kind", "state", "error", "started_at", "is_test", "delivery_unknown", "approval_id",
        ]);
        run.logs = await this.orm.searchRead("workflow.run.log", [["run_id", "=", id]], ["name", "state", "message", "occurred_at"]);
        this.state.run = run;
    }
    operateRun(method, label) {
        this.dialog.add(ConfirmationDialog, {
            title: label,
            body: method === "action_retry_confirmed"
                ? "Confirm that you checked the destination and it did not process this delivery. Retrying may otherwise duplicate the external action."
                : label + "? Completed actions will not be undone.",
            confirm: async () => {
                await this.orm.call("workflow.run", method, [[this.state.run.id]]);
                await this.loadRuns();
            },
        });
    }
    triggerLabel(value) {
        return { manual: "Button / run manually", create: "Record created", write: "Record changed",
            stage: "Stage or status changed", date: "Date field", schedule: "Schedule", webhook: "Incoming webhook" }[value] || value;
    }
    edgeName(value) { return value ? value[1] : "Next step"; }
}
registry.category("actions").add("workflow_center.home", Workflows);
export class WorkflowRuns extends Workflows {
    static initialPage = "runs";
}
registry.category("actions").add("workflow_center.runs", WorkflowRuns);
