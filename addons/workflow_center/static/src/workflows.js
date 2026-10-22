import { Component, onWillStart, proxy, useProps } from "@odoo/owl";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { formView } from "@web/views/form/form_view";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { Layout } from "@web/search/layout";
import { SearchPanel } from "@web/search/search_panel/search_panel";
import { useSubEnv } from "@web/owl2/utils";
import { View } from "@web/views/view";
import { FormController } from "@web/views/form/form_controller";
import { getDefaultConfig } from "@web/views/view";
import { CallbackRecorder, useSetupAction } from "@web/search/action_hook";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

let nextInspectorId = 0;

export class Workflows extends Component {
    static template = "workflow_center.Workflows";
    static components = { Layout, View };
    props = useProps();
    setup() {
        this.inspectorId = `wf_builder_${++nextInspectorId}`;
        useSubEnv({
            config: { ...getDefaultConfig(), ...this.env.config },
            workflowInspectorTarget: `#${this.inspectorId} .wf_inspector_toolbar`,
        });
        this.stepBeforeLeave = new CallbackRecorder();
        useSetupAction({ beforeLeave: () => this.saveSelectedStep() });
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = proxy({
            page: this.constructor.initialPage || "home", data: { templates: [], workflows: [], models: [] },
            workflow: null, selected: null,
            busy: false,
        });
        // [kind, action type, label, icon, one-line description, hover help with an example]
        this.blocks = [
            { title: _t("Actions"), items: [
                ["action", "object_write", _t("Update record"), "edit", _t("Change fields on the record"),
                    _t("Set or change fields on the record the workflow runs on. Example: assign a salesperson or move the stage to Qualified.")],
                ["action", "object_create", _t("Create record"), "add", _t("Create a related record"),
                    _t("Create another record and fill its fields from this one. Example: create a project when a deal is won.")],
                ["action", "next_activity", _t("Schedule activity"), "calendar_today", _t("Give someone a to-do"),
                    _t("Add an activity with a due date for a person. Example: “Call the customer” due in 2 days, for the salesperson.")],
                ["action", "followers", _t("Add followers"), "group", _t("Subscribe people to the record"),
                    _t("Followers receive the record's messages and updates. Example: add the customer to a new project.")],
                ["action", "mail_post", _t("Email or Odoo message"), "mail", _t("Send an email or post a note"),
                    _t("Send an email from a template, or post a message or internal note on the record. Example: email the customer a payment reminder.")],
                ["action", "chat", _t("Provider chat"), "chat_bubble", _t("Message on a chat channel"),
                    _t("Send a message through a connected chat provider. Needs a provider integration before the workflow can be activated.")],
                ["action", "webhook", _t("Call webhook"), "link", _t("Send data to another system"),
                    _t("Send the record to another system's URL. Delivery is tracked; an uncertain delivery stops the run for review. Example: send a confirmed order to logistics.")],
                ["action", "code", _t("Python code"), "code", _t("Run reviewed code"),
                    _t("Run Python code written by an administrator. Use only when no other step fits; it is checked again before activation.")],
            ] },
            { title: _t("Logic"), items: [
                ["condition", "object_write", _t("Condition"), "filter_alt", _t("Continue only if it matches"),
                    _t("Check the record against a filter. If it matches, continue; if not, this run stops here. Example: only posted, unpaid invoices.")],
                ["branch", "object_write", _t("Branch"), "account_tree", _t("Split into Yes and No"),
                    _t("Check a filter and follow a Yes path or a No path. Example: paid yet? Yes → thank the customer, No → call them.")],
                ["wait", "object_write", _t("Wait"), "schedule", _t("Pause for a time or until a date"),
                    _t("Pause the run for some hours or days, or until a date on the record, then continue. Example: wait 7 days.")],
                ["foreach", "object_write", _t("For each record"), "autorenew", _t("Repeat for related records"),
                    _t("Run an action once for each related record. Example: for each order line, update its delivery date.")],
            ] },
            { title: _t("Optional"), items: [["approval", "object_write", _t("Approval"), "checklist", _t("Wait for approvers"),
                _t("Ask the approvers of an approval type to accept before continuing. Refusal stops the run. Put the action to approve after this step.")]] },
        ];
        onWillStart(async () => {
            await this.loadHome();
            if (this.props.action.params?.workflow_id) {
                await this.openWorkflow(this.props.action.params.workflow_id);
            }
        });
    }
    async loadHome() {
        this.state.data = await this.orm.call("workflow.definition", "home_data", []);

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
        this.env.config.setDisplayName(this.state.workflow.name);
        this.state.page = "builder";
        if (this.state.selected !== "trigger" && !this.state.workflow.steps.some(s => s.id === this.state.selected)) this.state.selected = null;
    }
    async configureWorkflow() {
        if (this.state.selected === "trigger" || !await this.saveSelectedStep()) return;
        this.state.selected = "trigger";
    }
    async saveSelectedStep() {
        for (const callback of this.stepBeforeLeave.callbacks) {
            if (await callback() === false) return false;
        }
        return true;
    }
    async configureStep(step) {
        if (this.state.selected === step.id || !await this.saveSelectedStep()) return;
        this.state.selected = step.id;
    }
    async closeStep() {
        if (await this.saveSelectedStep()) this.state.selected = null;
    }
    get stepViewProps() {
        const isTrigger = this.state.selected === "trigger";
        return {
            type: "form", resModel: isTrigger ? "workflow.definition" : "workflow.step",
            resId: isTrigger ? this.state.workflow.id : this.state.selected,
            context: { form_view_ref: isTrigger ? "workflow_center.workflow_inspector_form" : "workflow_center.step_inspector_form" },
            jsClass: "workflow_inline_step", display: { controlPanel: false },
            preventCreate: true, readonly: this.state.workflow.state === "active",
            __beforeLeave__: this.stepBeforeLeave,
            removeRecord: isTrigger ? undefined : () => this.removeStep(this.selectedStep),
            onSave: () => this.openWorkflow(this.state.workflow.id),
        };
    }
    /**
     * Where a clicked step goes: after the selected step; first when the
     * trigger is selected or there are no steps; otherwise after the last step
     * of the main path. Null when that would be ambiguous (the main path ends
     * with a branch): the person then picks a step first.
     */
    get insertTarget() {
        const steps = this.state.workflow?.steps || [];
        if (this.selectedStep) {
            return { id: this.selectedStep.id, label: _t("Adds after “%s”.", this.selectedStep.name) };
        }
        if (this.state.selected === "trigger" || !steps.length) {
            return { id: false, label: _t("Adds as the first step.") };
        }
        const main = this.canvas.nodes;
        const last = main[main.length - 1];
        if (last && last.step.kind !== "branch") {
            return { id: last.step.id, label: _t("Adds at the end, after “%s”.", last.step.name) };
        }
        return null;
    }
    async addFromPalette(item) {
        const target = this.insertTarget;
        if (!target) {
            this.notification.add(_t("Click the step it should follow on the canvas, then add it, or drag it onto that step."), { type: "info" });
            return;
        }
        await this.addStep(item, target.id);
    }
    async addStep(item, afterId = this.selectedStep?.id || false) {
        if (this.state.busy || this.state.workflow.state === "active") return;
        this.state.busy = true;
        try {
            if (!await this.saveSelectedStep()) return;
            const id = await this.orm.call("workflow.definition", "add_step", [[this.state.workflow.id], item[0], item[1], afterId]);
            await this.openWorkflow(this.state.workflow.id);
            this.state.selected = id;
        } finally {
            this.state.busy = false;
        }
    }
    startStepDrag(ev, item) {
        if (this.state.workflow.state === "active" || this.state.busy) {
            ev.preventDefault();
            return;
        }
        this.draggedStep = item;
        ev.dataTransfer.effectAllowed = "copy";
        ev.dataTransfer.setData("application/x-workflow-step", item[0] + ":" + item[1]);
    }
    allowStepDrop(ev) {
        if (!this.draggedStep || this.state.workflow.state === "active" || this.state.busy) return;
        ev.preventDefault();
        ev.stopPropagation();
        ev.dataTransfer.dropEffect = "copy";
    }
    async dropStep(ev, afterId) {
        if (!this.draggedStep) return;
        ev.preventDefault();
        ev.stopPropagation();
        this.clearDropTarget();
        const item = this.draggedStep;
        this.draggedStep = null;
        if (afterId === undefined) {
            // Dropped on the canvas background: same rule as a click.
            const target = this.insertTarget;
            if (!target) {
                this.notification.add(_t("Drop the step onto the step it should follow."), { type: "info" });
                return;
            }
            afterId = target.id;
        }
        await this.addStep(item, afterId);
    }
    markDropTarget(ev) {
        if (!this.draggedStep) return;
        this.clearDropTarget();
        ev.currentTarget.classList.add("wf_drop_target");
    }
    clearDropTarget() {
        document.querySelectorAll(".wf_drop_target").forEach((el) => el.classList.remove("wf_drop_target"));
    }
    async removeStep(step) {
        if (this.state.workflow.state === "active") return;
        if (this.state.selected !== step.id && !await this.saveSelectedStep()) return;
        this.dialog.add(ConfirmationDialog, {
            title: "Remove step", body: "Remove this step from the draft? If another branch points here, update that branch first.",
            confirm: async () => {
                await this.orm.unlink("workflow.step", [step.id]);
                await this.openWorkflow(this.state.workflow.id);
            },
        });
    }
    async testRun() {
        if (!await this.saveSelectedStep()) return;
        const action = await this.orm.call("workflow.definition", "action_test_dialog", [[this.state.workflow.id]]);
        await this.action.doAction(action, { onClose: () => this.openWorkflow(this.state.workflow.id) });
    }
    async activate() {
        if (!await this.saveSelectedStep()) return;
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
    resizeStepPanel(ev) {
        const panel = ev.currentTarget.previousElementSibling;
        // Reuse the native search-panel drag bounds and pointer cleanup.
        SearchPanel.prototype._onStartResize.call({ root: () => panel }, ev);
    }
    triggerLabel(value) {
        return { manual: "Button / run manually", create: "Record created", write: "Record changed",
            stage: "Stage or status changed", date: "Date field", schedule: "Schedule", webhook: "Incoming webhook" }[value] || value;
    }
    edgeName(value) { return value ? value[1] : "Next step"; }
    /** True when a Yes/No path stops on its own, so it does not join the shared continuation. */
    pathEnds(nodes) {
        const last = nodes[nodes.length - 1];
        return Boolean(last && last.step.end);
    }
}
// Keep the native form widgets, validation, and Save/Discard behavior in the inspector.
class WorkflowInlineStepController extends FormController {
    static template = "workflow_center.InlineStepForm";
    setup() {
        // Embedded records must not overwrite the enclosing workflow breadcrumb.
        useSubEnv({ config: { ...this.env.config, setDisplayName: () => {} } });
        super.setup();
    }
    get hasInspectorActions() {
        const data = this.model.root.data;
        return this.props.resModel === "workflow.step" && !this.props.readonly
            && ["action", "foreach"].includes(data.kind) && data.action_type !== "object_create";
    }
}
registry.category("views").add("workflow_inline_step", {
    ...formView, Controller: WorkflowInlineStepController,
});
registry.category("actions").add("workflow_center.builder", Workflows);
registry.category("actions").add("workflow_center.home", (env, action) =>
    env.services.action.doAction(action.params?.workflow_id
        ? { type: "ir.actions.client", tag: "workflow_center.builder", name: action.name, params: action.params }
        : "workflow_center.action_workflow_templates")
);
registry.category("actions").add("workflow_center.runs", (env) =>
    env.services.action.doAction("workflow_center.action_run_history")
);

// Preserve existing My workflows bookmarks while using native collection views.
registry.category("actions").add("workflow_center.my_workflows", (env) =>
    env.services.action.doAction("workflow_center.action_workflow_library")
);

registry.category("actions").add("workflow_center.new", (env) =>
    env.services.action.doAction({
        type: "ir.actions.act_window", name: "New workflow",
        res_model: "workflow.definition", views: [[false, "form"]], target: "current",
    })
);

export class WorkflowStarter extends Component {
    static template = "workflow_center.WorkflowStarter";
    props = useProps(standardWidgetProps);

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ models: [], modelId: "", description: "", busy: false, agents: [], agentId: "", aiDrafting: false });
        onWillStart(async () => {
            if (this.props.record.resId) return;
            const data = await this.orm.call("workflow.definition", "home_data", []);
            this.state.models = data.models;
            this.state.agents = data.agents || [];
            this.state.aiDrafting = Boolean(data.ai_drafting);
            this.state.agentId = this.state.agents.length ? String(this.state.agents[0].id) : "";
            const selected = this.props.record.data.model_id?.id;
            const model = data.models.find(m => m.id === selected)
                || data.models.find(m => m.model === "account.move")
                || data.models.find(m => m.model === "res.partner") || data.models[0];
            this.state.modelId = model ? String(model.id) : "";
            this.state.description = this.props.record.data.description || "";
        });
    }

    async draftWithAi() {
        if (this.state.busy || !this.state.description.trim() || !this.state.modelId || !this.state.agentId) return;
        this.state.busy = true;
        try {
            const action = await this.orm.call("workflow.definition", "ai_draft", [
                this.state.description.trim(), Number(this.state.modelId), Number(this.state.agentId),
            ]);
            await this.action.doAction(action);
        } finally {
            this.state.busy = false;
        }
    }

    async startBlank() {
        if (this.state.busy || this.props.record.resId || this.props.readonly) return;
        const model = this.state.models.find(m => String(m.id) === this.state.modelId);
        if (!model) return;
        this.state.busy = true;
        try {
            await this.props.record.update({
                model_id: { id: model.id, display_name: model.name },
                description: this.state.description,
            });
        } finally {
            this.state.busy = false;
        }
    }
}
registry.category("view_widgets").add("workflow_starter", { component: WorkflowStarter });

export class WorkflowListController extends ListController {
    createRecord() {
        return this.actionService.doAction("workflow_center.action_new_workflow");
    }
}
registry.category("views").add("workflow_center_list", {
    ...listView,
    Controller: WorkflowListController,
});

registry.category("views").add("workflow_center_form", {
    ...formView,
    buttonTemplate: "workflow_center.FormButtons",
});

class WorkflowTemplateKanbanController extends KanbanController {
    createRecord() {
        return this.actionService.doAction("workflow_center.action_new_workflow");
    }
}
registry.category("views").add("workflow_template_kanban", {
    ...kanbanView,
    Controller: WorkflowTemplateKanbanController,
    buttonTemplate: "workflow_center.TemplateButtons",
});
registry.category("views").add("workflow_template_list", {
    ...listView,
    Controller: WorkflowListController,
    buttonTemplate: "workflow_center.TemplateButtons",
});
