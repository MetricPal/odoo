import { Component, onWillDestroy, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { X2ManyField, x2ManyField } from "@web/views/fields/x2many/x2many_field";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/** "8 s", "1 min 5 s": the same wording as Home's waiting line. */
export function waitedText(seconds) {
    seconds = Math.max(Math.floor(seconds), 0);
    return seconds < 60 ? _t("%s s", seconds) : _t("%(m)s min %(s)s s", { m: Math.floor(seconds / 60), s: seconds % 60 });
}

/** What the grey line says while the assistant works (Home's steps: 10 s, 30 s). */
export function waitingText(label, seconds) {
    if (seconds >= 30) {
        return _t("Still working on it; the AI service is slow right now.");
    }
    return seconds >= 10 ? _t("This is taking a bit longer than usual…") : label;
}

/**
 * The slides of a carousel (board 13.3): a click on a row makes it the slide being edited next to the preview,
 * instead of opening it. The design is saved first, so nothing typed on the previous slide is lost.
 */
export class SlidesField extends X2ManyField {
    async openRecord(record) {
        const design = this.props.record;
        if (!record.resId || design.data.active_slide_id?.id === record.resId) {
            return;
        }
        if (await design.save()) {
            await design.update({ active_slide_id: { id: record.resId, display_name: "" } });
            await design.save();
        }
    }
}

registry.category("fields").add("mi_slides", { ...x2ManyField, component: SlidesField });

const FORMAT_PIXELS = {
    square: [1080, 1080],
    portrait: [1080, 1350],
    story: [1080, 1920],
    carousel: [1080, 1350],
    poster: [2480, 3508],
    email_header: [1200, 400],
};

const FORMAT_SHAPES = {
    square: [34, 34, "1080 × 1080"],
    portrait: [28, 35, "1080 × 1350"],
    story: [20, 36, "1080 × 1920"],
    carousel: [28, 35, _t("2 to 10 slides")],
    poster: [25, 36, "A4 / A3"],
    email_header: [54, 18, "1200 × 400"],
};

/** New design, step 1 (board 13.2): the formats as tiles with their shape and size. */
export class FormatTiles extends Component {
    static template = "marketing_intel_design.FormatTiles";
    props = useProps({ ...standardFieldProps });

    get options() {
        return this.props.record.fields[this.props.name].selection.map(([value, label]) => {
            const [width, height, size] = FORMAT_SHAPES[value] || [30, 30, ""];
            return { value, label, size, style: `width:${width}px;height:${height}px` };
        });
    }
    get value() { return this.props.record.data[this.props.name]; }
    pick(value) { this.props.record.update({ [this.props.name]: value }); }
}

registry.category("fields").add("mi_format_tiles", { component: FormatTiles, supportedTypes: ["selection"] });

/** New design, step 2 (board 13.2): the templates as pictures drawn in the chosen format with the brand kit. */
export class TemplateTiles extends Component {
    static template = "marketing_intel_design.TemplateTiles";
    props = useProps({ ...standardFieldProps, formatField: t.string(), brandField: t.string() });

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ templates: [] });
        onWillStart(async () => {
            this.state.templates = await this.orm.searchRead("mi.design.template", [], ["name", "description"]);
        });
    }
    get value() { return this.props.record.data[this.props.name]; }
    /** The tile's picture is drawn 220 px wide in the chosen format: its size is given so the page does not jump. */
    get sampleWidth() { return 220; }
    get sampleHeight() {
        const [width, height] = FORMAT_PIXELS[this.props.record.data[this.props.formatField]] || [1, 1];
        return Math.round((220 * height) / width);
    }
    src(template) {
        const data = this.props.record.data;
        return `/marketing_intel_design/template/${template.id}/${data[this.props.formatField]}`
            + `?brand_id=${data[this.props.brandField]?.id || 0}`;
    }
    pick(template) {
        this.props.record.update({ [this.props.name]: { id: template.id, display_name: template.name } });
    }
}

registry.category("fields").add("mi_template_tiles", {
    component: TemplateTiles,
    supportedTypes: ["many2one"],
    extractProps: ({ options }) => ({
        formatField: options.format_field || "format",
        brandField: options.brand_field || "brand_id",
    }),
});

const USE_TARGETS = [
    ["social", _t("A social post"), "action_use_social"],
    ["email", _t("An email"), "action_use_email"],
    ["proof", _t("A proof for review"), "action_use_proof"],
];

/** Use in ▾ on a design (board 13.4 B): only what the person may make and what fits the format. */
export class DesignUse extends Component {
    static template = "marketing_intel_design.DesignUse";
    static components = { Dropdown, DropdownItem };
    props = useProps({ ...standardWidgetProps });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }
    get targets() {
        const allowed = (this.props.record.data.use_targets || "").split(",");
        return USE_TARGETS.filter(([key]) => allowed.includes(key));
    }
    async use(method) {
        const record = this.props.record;
        if (!(await record.save())) {
            return;
        }
        const action = await this.orm.call("mi.design", method, [[record.resId]]);
        if (action && typeof action === "object") {
            this.action.doAction(action, { onClose: () => record.load() });
        }
    }
}

registry.category("view_widgets").add("mi_design_use", { component: DesignUse });

/**
 * The grey line while the Marketing assistant works on a design (a picture, the texts): the time waited, with
 * Home's slow wording, and the form reloads itself when the answer is in.
 */
export class DesignWait extends Component {
    static template = "marketing_intel_design.DesignWait";
    props = useProps({
        ...standardWidgetProps,
        stateField: t.string(),
        waiting: t.string(),
        sinceField: t.string(),
        label: t.string(),
    });

    setup() {
        this.state = proxy({ now: Date.now() });
        this.timer = setInterval(() => this.tick(), 1000);
        this.ticks = 0;
        onWillDestroy(() => clearInterval(this.timer));
    }
    get isWaiting() { return this.props.record.data[this.props.stateField] === this.props.waiting; }
    get seconds() {
        const since = this.props.record.data[this.props.sinceField];
        return since ? (this.state.now - since.toMillis()) / 1000 : 0;
    }
    get text() { return waitingText(this.props.label, this.seconds); }
    get waited() { return waitedText(this.seconds); }
    async tick() {
        if (!this.isWaiting) {
            return;
        }
        this.state.now = Date.now();
        this.ticks += 1;
        // Every 2 s, and never over something the person is typing.
        if (this.ticks % 2 === 0 && !this.props.record.dirty && !this.loading) {
            this.loading = true;
            try {
                await this.props.record.load();
            } finally {
                this.loading = false;
            }
        }
    }
}

registry.category("view_widgets").add("mi_design_wait", {
    component: DesignWait,
    extractProps: ({ attrs }) => ({
        stateField: attrs.state_field,
        waiting: attrs.waiting,
        sinceField: attrs.since_field,
        label: attrs.label,
    }),
});
