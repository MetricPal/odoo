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
    async dropStep(ev, afterId = this.selectedStep?.id || false) {
        if (!this.draggedStep) return;
        ev.preventDefault();
        ev.stopPropagation();
        const item = this.draggedStep;
        this.draggedStep = null;
        await this.addStep(item, afterId);
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
        this.state = proxy({ models: [], modelId: "", description: "", busy: false });
        onWillStart(async () => {
            if (this.props.record.resId) return;
            const data = await this.orm.call("workflow.definition", "home_data", []);
            this.state.models = data.models;
            const selected = this.props.record.data.model_id?.id;
            const model = data.models.find(m => m.id === selected)
                || data.models.find(m => m.model === "account.move")
                || data.models.find(m => m.model === "res.partner") || data.models[0];
            this.state.modelId = model ? String(model.id) : "";
            this.state.description = this.props.record.data.description || "";
        });
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
