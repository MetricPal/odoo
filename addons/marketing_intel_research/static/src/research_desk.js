import { Component, onWillStart, onWillUnmount, proxy, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export const UPDATED = "mi_research/updated";

/** Above the questions (board 12.6, banners from 12.3): web search is off, or no Marketing assistant is ready.
 * Questions are asked in the assistant's chat ("Ask a research question" in the control panel). */
export class ResearchBanners extends Component {
    static template = "marketing_intel_research.Banners";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = proxy({ desk: null });
        onWillStart(async () => {
            this.state.desk = await this.orm.call("mi.research", "get_desk", []);
        });
    }

    async openProfile() {
        this.action.doAction(await this.orm.call("mi.research", "action_open_profile", [[]]));
    }

    openAiAgent() {
        this.action.doAction(this.state.desk.ai_agent_action);
    }

    get webOffText() {
        return this.state.desk.ai_manager ? "" : _t("Ask an AI Agent manager to switch it on.");
    }
}

export class ResearchListRenderer extends ListRenderer {
    static template = "marketing_intel_research.ListRenderer";
    static components = { ...ListRenderer.components, ResearchBanners };

    setup() {
        super.setup();
        const bus = useService("bus_service");
        const unsubscribe = bus.subscribe(UPDATED, () => this.reload());
        onWillUnmount(() => unsubscribe?.());
    }

    async reload() {
        await this.props.list.load();
    }
}

registry.category("views").add("mi_research_list", { ...listView, Renderer: ResearchListRenderer });

/** On an answer's form: the answer appears when the assistant finishes, without reloading the page. */
export class ResearchLive extends Component {
    static template = "marketing_intel_research.Live";
    props = useProps({ ...standardWidgetProps });

    setup() {
        const bus = useService("bus_service");
        const unsubscribe = bus.subscribe(UPDATED, (payload) => this.onUpdated(payload));
        onWillUnmount(() => unsubscribe?.());
    }

    async onUpdated(payload) {
        const record = this.props.record;
        if (!record.resId || record.isDirty) {
            return;
        }
        const followups = record.data.followup_ids?.records?.map((r) => r.resId) || [];
        if (payload.id === record.resId || followups.includes(payload.id)) {
            await record.load();
        }
    }
}

registry.category("view_widgets").add("mi_research_live", { component: ResearchLive });
