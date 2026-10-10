import { Component, useProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { proxy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { SearchPanel } from "@web/search/search_panel/search_panel";
import { useSetupAction } from "@web/search/action_hook";

const openSetup = (controller) => controller.actionService.doAction(
    "omni_channel.action_channel_setup", { additionalContext: controller.model.root.context }
);
class ChannelListArchParser extends listView.ArchParser {
    parse(...args) {
        const archInfo = super.parse(...args);
        // Odoo 20's renderer supports noOpen, but list XML's RNG rejects no_open.
        archInfo.noOpen = true;
        return archInfo;
    }
}
class ChannelListController extends ListController {
    createRecord() { return openSetup(this); }
}
class ChannelKanbanController extends KanbanController {
    createRecord() { return openSetup(this); }
}
export class ChannelSetupController extends FormController {
    static template = "omni_channel.ChannelSetup";
    setup() {
        super.setup();
        const completed = this.props.context.setup_completed_step_ids ||
            Array.from({ length: this.props.context.setup_completed_steps || 0 }, (_, i) => i);
        this.setupState = proxy({ step: this.props.state?.setupStep ?? (completed.length ? Math.max(...completed) : 0), busy: false,
            completed: this.props.state?.setupCompleted || completed });
        this.steps = [
            { title: "Prepare", hint: "Choose the channel, company and team.", about: "Give the channel a name, choose its type, and select the company and team that will use it." },
            { title: "Credentials", hint: "Connect and verify your account.", about: "Enter credentials here or choose an existing connection. For Telegram, paste the token from BotFather. Verification fills in the bot ID and public profile; you do not need to enter the bot ID or database name." },
            { title: "Connect & verify", hint: "Set up and check receiving.", about: "Enable receiving when the connection is ready, or choose Set up receiving later to continue with a draft." },
            { title: "Branding", hint: "Choose how the channel appears.", about: "Set the channel's display name and internal description. Public bot names and pictures are managed by the provider, not by these internal labels." },
            { title: "Team & apps", hint: "Review ownership and availability.", about: "Review the communication team and company chosen in Prepare. The Inbox is available now. Only installed, supported application integrations can be connected." },
            { title: "Test & go live", hint: "Review a test and activate explicitly.", about: "Send an incoming message from an authorized test user, then select its conversation to draft a test reply. Review and approve sending separately. Activation is an explicit action; Finish setup only saves configuration." },
        ];
        useSetupAction({ getLocalState: () => ({ setupStep: this.setupState.step, setupCompleted: this.setupState.completed }) });
    }
    async beforeExecuteActionButton(clickParams) {
        // Saving new credentials already verifies getMe. Do not issue a second
        // network request after that successful, committed save.
        const verifiesOnSave = clickParams.name === "action_setup_verify_bot" &&
            Boolean(this.model.root.data.setup_bot_token || this.model.root.data.setup_webhook_secret);
        const saved = await super.beforeExecuteActionButton(clickParams);
        if (saved !== false && verifiesOnSave) {
            await this.actionService.doAction({
                type: "ir.actions.client", tag: "display_notification",
                params: { title: "Bot verified", message: "Connection saved. Continue to Connect & verify.", type: "success" },
            });
            return false;
        }
        return saved;
    }
    async selectSetupStep(index) {
        if (index !== this.setupState.step && !this.setupState.completed.includes(index)) return;
        return this.goToStep(index);
    }
    async goToStep(index) {
        if (this.setupState.busy || index < 0 || index >= this.steps.length || index === this.setupState.step || (index > this.setupState.step + 1 && !this.setupState.completed.includes(index))) return;
        this.setupState.busy = true;
        try {
            // Native save validates required fields and enforces the existing access rules.
            if (await this.save()) {
                if (index > this.setupState.step) {
                    await this.orm.call("omni.channel", "action_setup_complete_step", [[this.model.root.resId], this.setupState.step]);
                    await this.model.load({ resId: this.model.root.resId });
                }
                if (index > this.setupState.step) {
                    this.setupState.completed = this.model.root.data.setup_completed_step_ids || [];
                }
                this.setupState.step = index;
            }
        } finally {
            this.setupState.busy = false;
        }
    }
    async deferReceiving() {
        if (this.setupState.busy) return;
        this.setupState.busy = true;
        try {
            if (await this.save()) {
                await this.orm.call("omni.channel", "action_setup_defer_receiving", [[this.model.root.resId]]);
                await this.model.load({ resId: this.model.root.resId });
                this.setupState.step = 3;
            }
        } finally { this.setupState.busy = false; }
    }
    async saveSetupDraft() {
        if (this.setupState.busy) return;
        this.setupState.busy = true;
        try {
            if (await this.save()) await this.actionService.doAction("omni_channel.action_channels");
        } finally { this.setupState.busy = false; }
    }
    resizeSteps(ev) {
        const panel = ev.currentTarget.previousElementSibling;
        SearchPanel.prototype._onStartResize.call({ root: () => panel }, ev);
    }
    async finishSetup() {
        if (this.setupState.busy) return;
        this.setupState.busy = true;
        try {
            if (await this.save()) {
                await this.orm.call("omni.channel", "action_setup_complete_step", [[this.model.root.resId], 5]);
                await this.actionService.doAction({ type: "ir.actions.act_window", res_model: "omni.channel",
                    res_id: this.model.root.resId, views: [[false, "form"]], target: "current" });
            }
        } finally { this.setupState.busy = false; }
    }
}
registry.category("views").add("omni_channel_setup", { ...formView, Controller: ChannelSetupController });
registry.category("views").add("omni_channel_list", { ...listView, ArchParser: ChannelListArchParser, Controller: ChannelListController });
registry.category("views").add("omni_channel_kanban", { ...kanbanView, Controller: ChannelKanbanController });

// A generated URL remains selectable as an input without editing deployment settings.
class CallbackInput extends Component {
    static template = "omni_channel.CallbackInput";
    props = useProps(standardFieldProps);
}
registry.category("fields").add("omni_callback_input", {
    component: CallbackInput,
    supportedTypes: ["char"],
});
