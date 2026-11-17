import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { Layout } from "@web/search/layout";
import { Component, onWillStart, proxy, useProps } from "@odoo/owl";

const PERIODS = [
    ["month", "This month"],
    ["quarter", "This quarter"],
    ["year", "This year"],
];
const KIND_LABELS = {
    approvals: "Approval waiting",
    late: "Late",
    todo: "To do",
    channels: "Channel",
    alerts: "Alert",
    automations: "Automation",
    setup: "Setup",
};

/**
 * The Marketing home page, "Today" (boards 18.1 to 18.3): what needs the person first, a few numbers, what is running
 * and a side column; a Junior sees "My day". One server call draws it all.
 */
export class MarketingToday extends Component {
    static template = "marketing_intel_plan.Today";
    static components = { Layout, Dropdown, DropdownItem };
    props = useProps();

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.periods = PERIODS;
        this.state = proxy({ data: null, period: "quarter", filter: "all" });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("mi.panel", "get_today", [], { period: this.state.period });
    }
    async setPeriod(period) {
        this.state.period = period;
        await this.load();
    }
    setFilter(kind) {
        this.state.filter = kind;
    }

    get kindLabel() {
        return KIND_LABELS;
    }
    get items() {
        const all = this.state.data.attention.items;
        return this.state.filter === "all" ? all : all.filter((item) => item.kind === this.state.filter);
    }
    get subtitle() {
        const d = this.state.data;
        const parts = [];
        if (d.title !== "Marketing") {
            parts.push(d.title);
        }
        if (d.role_label) {
            parts.push(d.role_label);
        }
        parts.push(d.today);
        return parts.join(" · ");
    }
    pct(setup) {
        return setup.total ? Math.round((100 * setup.done) / setup.total) : 0;
    }

    // ------------------------------------------------------------------ going places

    openTarget(target) {
        if (target.action) {
            return this.go(target.action);
        }
        if (target.model && target.res_id) {
            return this.open(target.model, target.res_id);
        }
    }
    open(model, resId) {
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: model, res_id: resId, views: [[false, "form"]], target: "current",
        });
    }
    async go(xmlid) {
        try {
            return await this.action.doAction(xmlid);
        } catch {
            return this.action.doAction("marketing_intel_plan.action_plans");
        }
    }
    newCampaign() {
        return this.action.doAction({
            type: "ir.actions.act_window", res_model: "mi.plan", views: [[false, "form"]], target: "current",
        });
    }
    async askAssistant() {
        const channelId = await this.orm.call("mi.panel", "open_assistant_chat", []);
        const channel = await this.env.services["mail.store"]["discuss.channel"].getOrFetch(channelId);
        channel?.open({ focus: true });
    }
    makeButton(button) {
        return button.chat ? this.askAssistant() : this.go(button.action);
    }
}

registry.category("actions").add("marketing_intel_plan.today", MarketingToday);
