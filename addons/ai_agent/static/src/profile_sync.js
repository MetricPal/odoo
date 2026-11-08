import { Component, onWillUnmount, proxy, useProps } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/** Sync to Hermes, which reads "Syncing…" while it runs (approved mock 2026-11-08, board 15). */
export class ProfileSyncButton extends Component {
    static template = "ai_agent.ProfileSyncButton";
    props = useProps({ ...standardWidgetProps });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ busy: false });
    }

    async sync() {
        if (this.state.busy) {
            return;
        }
        const record = this.props.record;
        this.state.busy = true;
        try {
            if (await record.save()) {
                await this.orm.call("ai.agent.profile", "action_sync", [[record.resId]]);
            }
        } finally {
            this.state.busy = false;
            await record.load();
        }
    }
}

/** The steps of Sync to Hermes as the server reports them, with the seconds of the model test. */
export class ProfileSyncProgress extends Component {
    static template = "ai_agent.ProfileSyncProgress";
    props = useProps({ ...standardWidgetProps });

    setup() {
        this.state = proxy({ step: 0, total: 0, steps: [], seconds: 0, running: false });
        const bus = useService("bus_service");
        const unsubscribe = bus.subscribe("ai_agent/sync_progress", (payload) => this.onProgress(payload));
        onWillUnmount(() => {
            unsubscribe?.();
            clearInterval(this.timer);
        });
    }

    onProgress(payload) {
        if (payload.profile_id !== this.props.record.resId) {
            return;
        }
        clearInterval(this.timer);
        if (payload.state === "done") {
            this.state.running = false;
            return;
        }
        Object.assign(this.state, {
            step: payload.step, total: payload.total, steps: payload.steps, running: true, seconds: 0,
        });
        if (payload.step === payload.total) {
            // The model test can take up to 30 seconds: count them.
            this.timer = setInterval(() => this.state.seconds++, 1000);
        }
    }

    get percent() {
        return this.state.total ? Math.round(((this.state.step - 0.5) / this.state.total) * 100) : 0;
    }
}

registry.category("view_widgets").add("ai_agent_profile_sync", { component: ProfileSyncButton });
registry.category("view_widgets").add("ai_agent_profile_sync_progress", { component: ProfileSyncProgress });
