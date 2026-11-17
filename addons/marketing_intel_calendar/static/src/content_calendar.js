import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dialog } from "@web/core/dialog/dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { formatDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { CalendarCommonPopover } from "@web/views/calendar/calendar_common/calendar_common_popover";
import { CalendarCommonRenderer } from "@web/views/calendar/calendar_common/calendar_common_renderer";
import { CalendarController } from "@web/views/calendar/calendar_controller";
import { CalendarModel } from "@web/views/calendar/calendar_model";
import { CalendarRenderer } from "@web/views/calendar/calendar_renderer";
import { calendarView } from "@web/views/calendar/calendar_view";
import { ListController } from "@web/views/list/list_controller";
import { listView } from "@web/views/list/list_view";

const { DateTime } = luxon;

/** The time a new item gets from a clicked day: 09:00 that day; none when that is already past. */
export function plannedTime(start, isAllDay) {
    if (!start) {
        return false;
    }
    const when = isAllDay ? start.set({ hour: 9, minute: 0, second: 0 }) : start;
    return when > DateTime.now() ? serializeDateTime(when) : false;
}

/** A click on an empty day (board 14.1): which kind of content to make for that day. */
export class NewContentDialog extends Component {
    static template = "marketing_intel_calendar.NewContentDialog";
    static components = { Dialog };
    props = useProps({
        options: t.array(),
        day: t.string(),
        onPick: t.function(),
        close: t.function(),
    });

    pick(kind) {
        this.props.close();
        this.props.onPick(kind);
    }
}

/** An item's popover (board 14.2 A): Open goes to the item in its own app; nothing is edited or deleted here. */
export class ContentPopover extends CalendarCommonPopover {
    static defaultFooterButtonsTemplate = "marketing_intel_calendar.PopoverButtons";
}

export class ContentCommonRenderer extends CalendarCommonRenderer {
    static components = { ...CalendarCommonRenderer.components, Popover: ContentPopover };
}

export class ContentRenderer extends CalendarRenderer {
    static components = {
        ...CalendarRenderer.components,
        day: ContentCommonRenderer,
        week: ContentCommonRenderer,
        month: ContentCommonRenderer,
    };
}

/** Dragging an item (board 14.2 B): a scheduled one asks first; what its app refuses goes back where it was. */
export class ContentModel extends CalendarModel {
    /**
     * The filter panel lists every channel and campaign (up to 100), not only those with an item in the dates on
     * screen, so a period without content does not leave the panel empty.
     */
    async loadDynamicFilterSection(data, fieldName, filterInfo, previousSection) {
        const section = await super.loadDynamicFilterSection(data, fieldName, filterInfo, previousSection);
        const field = this.meta.fields[fieldName];
        if (!field?.relation) {
            return section;
        }
        const colorName = filterInfo.colorFieldName;
        const records = await this.orm.searchRead(
            field.relation,
            [],
            colorName ? ["display_name", colorName] : ["display_name"],
            { limit: 100 }
        );
        const have = new Set(section.filters.map((filter) => filter.value));
        const previous = previousSection ? previousSection.filters : [];
        for (const record of records) {
            if (have.has(record.id)) {
                continue;
            }
            section.filters.push(
                this.makeFilterDynamic(
                    filterInfo,
                    previous.find((filter) => filter.type === "dynamic" && filter.value === record.id),
                    fieldName,
                    { id: record.id, [fieldName]: [record.id, record.display_name] },
                    colorName ? records : []
                )
            );
        }
        // Items without a campaign are always one of the choices
        if (fieldName === "plan_id" && !have.has(false)) {
            section.filters.push(
                this.makeFilterDynamic(
                    filterInfo,
                    previous.find((filter) => filter.type === "dynamic" && filter.value === false),
                    fieldName,
                    { id: false, [fieldName]: false },
                    []
                )
            );
        }
        // "Undefined" stays first, the others by name
        section.filters.sort((a, b) =>
            !b.value - !a.value || String(a.label).localeCompare(String(b.label))
        );
        return section;
    }

    async updateRecord(record, options = {}) {
        const current = this.records[record.id];
        if (current?.rawRecord.status === "scheduled" && !(await this.confirmMove(current, record))) {
            await this.load();
            return;
        }
        try {
            await super.updateRecord(record, options);
        } catch (error) {
            await this.load();
            throw error;
        }
    }

    confirmMove(current, moved) {
        const format = (value) => formatDateTime(value, { format: "ccc d LLL, HH:mm" });
        return new Promise((resolve) => {
            this.env.services.dialog.add(ConfirmationDialog, {
                title: _t("Move “%s”?", current.title),
                body: _t(
                    "It is scheduled for %(from)s. Move it to %(to)s? It stays scheduled and goes out at the new time.",
                    { from: format(current.start), to: format(moved.start) }
                ),
                confirmLabel: _t("Move"),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
    }
}

export class ContentController extends CalendarController {
    static components = { ...CalendarController.components, Dropdown, DropdownItem };

    setup() {
        super.setup();
        this.contentOrm = useService("orm");
        this.contentAction = useService("action");
        this.contentDialog = useService("dialog");
        this.newContent = proxy({ options: [] });
        onWillStart(async () => {
            this.newContent.options = await this.contentOrm.call("mi.content", "new_options", []);
        });
    }

    get className() {
        return `${super.className || ""} o_mi_content_calendar`;
    }

    /** New: the app's own form, with the day filled in. */
    async newItem(kind, when = false) {
        this.contentAction.doAction(await this.contentOrm.call("mi.content", "action_new", [kind, when]));
    }

    /** A click on an empty day asks which kind, then does the same. */
    createRecord(record) {
        if (!this.newContent.options.length) {
            return;
        }
        this.contentDialog.add(NewContentDialog, {
            options: this.newContent.options,
            day: formatDateTime(record.start, { format: "cccc d LLLL" }),
            onPick: (kind) => this.newItem(kind, plannedTime(record.start, record.isAllDay)),
        });
    }

    /** Open: the item in its own app. */
    async editRecord(record) {
        this.contentAction.doAction(await this.contentOrm.call("mi.content", "action_open", [[record.id]]));
    }
}

registry.category("views").add("mi_content_calendar", {
    ...calendarView,
    Controller: ContentController,
    Model: ContentModel,
    Renderer: ContentRenderer,
    buttonTemplate: "marketing_intel_calendar.NewButton",
});

/** The same content as a list (board 14.2 C): a row opens the item in its own app. */
export class ContentListController extends ListController {
    async openRecord(record) {
        const action = await this.model.orm.call("mi.content", "action_open", [[record.resId]]);
        this.actionService.doAction(action);
    }
}

registry.category("views").add("mi_content_list", { ...listView, Controller: ContentListController });
