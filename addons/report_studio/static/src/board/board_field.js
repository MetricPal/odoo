import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSortable } from "@web/core/utils/sortable_owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { Component, markup, signal, useProps } from "@odoo/owl";

const MM_TO_PX = 96 / 25.4;

export const BOX_TYPES = [
    ["heading", _t("Title"), "title"],
    ["text", _t("Text"), "notes"],
    ["kpi", _t("Number"), "pin"],
    ["chart", _t("Chart"), "bar_chart"],
    ["table", _t("Table"), "table"],
    ["list", _t("List"), "list"],
    ["image", _t("Image"), "image"],
    ["link", _t("Hyperlink"), "link"],
];

/**
 * Report board: boxes on a 4-column page. Add, drag to reorder, resize (1-4 columns),
 * edit in a dialog, remove. Box content is rendered by the server so that the board,
 * the PDF and the HTML file look the same.
 */
export class ReportBoardField extends Component {
    static template = "report_studio.BoardField";
    static components = { Dropdown, DropdownItem };

    props = useProps({ ...standardFieldProps });
    gridRef = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.boxTypes = BOX_TYPES;
        useSortable({
            ref: this.gridRef,
            elements: ".o_rs_gbox",
            handle: ".o_rs_drag",
            cursor: "move",
            onDrop: ({ element, previous }) => this.moveBox(element, previous),
        });
    }

    get data() {
        return this.props.record.data[this.props.name] || { boxes: [], page: {} };
    }

    get boxes() {
        return (this.data.boxes || []).map((box) => ({ ...box, markup: markup(box.html || "") }));
    }

    get page() {
        return this.data.page || {};
    }

    get pageLabel() {
        const page = this.page;
        const fit = { actual: _t("actual size"), fit: _t("fit on one page"), fill: _t("fill the page") }[page.fit];
        return `${page.paper || ""} · ${page.orientation === "landscape" ? _t("landscape") : _t("portrait")} · ${fit || ""}`;
    }

    get canvasStyle() {
        const page = this.page;
        if (!page.width_mm) {
            return "";
        }
        const width = Math.round(page.width_mm * MM_TO_PX);
        const padding = Math.round(page.margin_mm * MM_TO_PX);
        return `width: ${width}px; padding: ${padding}px; --rs-accent: ${this.data.accent};`;
    }

    get pageBreakStyle() {
        const page = this.page;
        const top = Math.round((page.height_mm - page.margin_mm) * MM_TO_PX);
        return `top: ${top}px;`;
    }

    get readonly() {
        // The board is a computed field (always "readonly" for the form); editability follows the record.
        return !this.props.record.isInEdition;
    }

    async ensureSaved() {
        const record = this.props.record;
        if (record.isNew || (await record.isDirty())) {
            const saved = await record.save();
            if (!saved) {
                return false;
            }
        }
        return record.resId;
    }

    async reload() {
        await this.props.record.load();
        this.props.record.model.notify();
    }

    async addBox(type) {
        const reportId = await this.ensureSaved();
        if (!reportId) {
            return;
        }
        const boxId = await this.orm.call("report.studio.report", "action_add_box", [[reportId], type]);
        await this.reload();
        this.editBox(boxId, true);
    }

    editBox(boxId, isNew = false) {
        this.dialog.add(FormViewDialog, {
            resModel: "report.studio.block",
            resId: boxId,
            title: isNew ? _t("New box") : _t("Edit box"),
            onRecordSaved: () => this.reload(),
        }, {
            onClose: () => this.reload(),
        });
    }

    async setWidth(box, width) {
        if (box.width === width) {
            return;
        }
        await this.ensureSaved();
        await this.orm.write("report.studio.block", [box.id], { width });
        await this.reload();
    }

    removeBox(box) {
        this.dialog.add(ConfirmationDialog, {
            body: _t("Remove “%s” from this report?", box.title || box.type_label),
            confirmLabel: _t("Remove"),
            confirm: async () => {
                await this.orm.unlink("report.studio.block", [box.id]);
                await this.reload();
            },
            cancel: () => {},
        });
    }

    async moveBox(element, previous) {
        const ids = this.boxes.map((box) => box.id);
        const moved = parseInt(element.dataset.id, 10);
        const order = ids.filter((id) => id !== moved);
        const index = previous ? order.indexOf(parseInt(previous.dataset.id, 10)) + 1 : 0;
        order.splice(index, 0, moved);
        const reportId = await this.ensureSaved();
        await this.orm.call("report.studio.report", "action_reorder_boxes", [[reportId], order]);
        await this.reload();
    }
}

export const reportBoardField = {
    component: ReportBoardField,
    supportedTypes: ["json"],
};

registry.category("fields").add("report_studio_board", reportBoardField);
