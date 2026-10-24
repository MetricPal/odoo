import { _t } from "@web/core/l10n/translation";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useAutofocus, useService } from "@web/core/utils/hooks";
import { Component, onWillStart, proxy, signal } from "@odoo/owl";

const cogMenuRegistry = registry.category("cogMenu");

export const EXPORT_FORMATS = [
    ["pdf", _t("PDF"), "picture_as_pdf"],
    ["xlsx", _t("Excel"), "table"],
    ["pptx", _t("PowerPoint"), "slideshow"],
    ["docx", _t("Word"), "description"],
    ["html", _t("HTML"), "code"],
];

/** ⋯ > Export > PDF / Excel / PowerPoint / Word / HTML on a report. */
export class ReportExportMenu extends Component {
    static template = "report_studio.ExportMenu";
    static components = { Dropdown, DropdownItem };

    setup() {
        this.formats = EXPORT_FORMATS;
    }

    async export(format) {
        // The menu closes (and this component goes away) on click: use the services directly.
        const { action, orm } = this.env.services;
        const record = this.env.model.root;
        if (record.isNew || (await record.isDirty())) {
            if (!(await record.save())) {
                return;
            }
        }
        const exportAction = await orm.call("report.studio.report", "action_export", [[record.resId], format]);
        await action.doAction(exportAction);
    }
}

cogMenuRegistry.add(
    "report-studio-export",
    {
        Component: ReportExportMenu,
        groupNumber: 5,
        isDisplayed: ({ config, searchModel }) =>
            config.viewType === "form" && searchModel.resModel === "report.studio.report",
    },
    { sequence: 1 }
);

/** ⋯ > Add to report, on any list, graph, pivot or kanban opened from a menu. */
export class AddToReport extends Component {
    static template = "report_studio.AddToReport";
    static components = { Dropdown };

    autofocusRef = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = proxy({ name: this.env.config.getDisplayName(), reportId: "new", newName: "", reports: [] });
        useAutofocus({ ref: this.autofocusRef });
        onWillStart(async () => {
            this.state.reports = await this.orm.searchRead("report.studio.report", [], ["name"], { limit: 40 });
            if (this.state.reports.length) {
                this.state.reportId = String(this.state.reports[0].id);
            }
        });
    }

    async add() {
        const { domain, globalContext } = this.env.searchModel;
        const { context, groupBys, orderBy } = this.env.searchModel.getPreFavoriteValues();
        const contextToSave = {
            ...Object.fromEntries(Object.entries(globalContext).filter(([key]) => !key.startsWith("search_default_"))),
            ...context,
            group_by: groupBys,
            orderedBy: orderBy,
        };
        const isNew = this.state.reportId === "new";
        if (isNew && !this.state.newName.trim()) {
            this.notification.add(_t("Give the new report a name."), { type: "warning" });
            return;
        }
        const result = await rpc("/report_studio/add_view", {
            action_id: this.env.config.actionId,
            context_to_save: contextToSave,
            domain,
            view_mode: this.env.config.viewType,
            name: this.state.name,
            report_id: isNew ? false : parseInt(this.state.reportId, 10),
            new_report: isNew ? this.state.newName.trim() : "",
        });
        this.notification.add(_t("Added to “%s”.", result.report_name), {
            type: "success",
            buttons: [{
                name: _t("Open report"),
                primary: true,
                onClick: () => this.action.doAction({
                    type: "ir.actions.act_window", res_model: "report.studio.report",
                    res_id: result.report_id, views: [[false, "form"]],
                }),
            }],
        });
    }
}

cogMenuRegistry.add(
    "report-studio-add-to-report",
    {
        Component: AddToReport,
        groupNumber: 10,
        isDisplayed: ({ config }) =>
            config.actionType === "ir.actions.act_window" && config.actionId &&
            ["list", "graph", "pivot", "kanban"].includes(config.viewType),
    },
    { sequence: 11 }
);
