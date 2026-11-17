import { Component, onWillStart, onWillDestroy, proxy, signal, useProps } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const MODEL = "mi.design.element";
const SAVED = ["kind", "x", "y", "w", "h", "text", "font", "bold", "size", "color", "align", "shape", "hidden",
    "locked", "sequence"];
const FIT = 520; // the longest side of the canvas at "Fit", in screen pixels
const MIN_SIDE = 2;

/**
 * The free editor of a design (board 16.1): the picture is drawn by the server, exactly as it is exported; this
 * widget puts a box over each element to select, move and resize it, and the panels to add, layer and describe
 * elements. Every change is written to the element at once; Undo / Redo walk back through them.
 */
export class DesignEditor extends Component {
    static template = "marketing_intel_design.DesignEditor";
    static components = { Dropdown, DropdownItem };
    props = useProps({ ...standardWidgetProps });

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = proxy({
            loaded: false, width: 1080, height: 1080, label: "", colors: {}, elements: [], selectedId: null,
            zoom: "fit", stamp: Date.now(), past: [], future: [], dragLayer: null, busy: false,
        });
        this.fileRef = signal.ref();
        this.drag = null;
        this.onMove = (ev) => this.dragMove(ev);
        this.onUp = (ev) => this.dragEnd(ev);
        onWillStart(() => this.load());
        onWillDestroy(() => this.stopDrag());
    }

    get designId() { return this.props.record.resId; }
    get scale() {
        const { zoom, width, height } = this.state;
        return zoom === "fit" ? FIT / Math.max(width, height) : Number(zoom) / 100;
    }
    get canvasStyle() {
        return `width:${Math.round(this.state.width * this.scale)}px;height:${Math.round(this.state.height * this.scale)}px`;
    }
    get imageSrc() {
        const width = Math.min(Math.max(Math.round(this.state.width * this.scale * 2), 240), 1600);
        return `/marketing_intel_design/${this.designId}/editor?w=${width}&t=${this.state.stamp}`;
    }
    get layers() { return [...this.state.elements].sort((a, b) => b.sequence - a.sequence || b.id - a.id); }
    get selected() { return this.state.elements.find((el) => el.id === this.state.selectedId); }
    get canUndo() { return this.state.past.length > 0; }
    get canRedo() { return this.state.future.length > 0; }
    get colorList() {
        return [["main", _t("Main")], ["accent", _t("Accent")], ["dark", _t("Dark")], ["light", _t("Light")]];
    }
    boxStyle(el) {
        const s = this.scale;
        return `left:${el.x * s}px;top:${el.y * s}px;width:${el.w * s}px;height:${el.h * s}px`;
    }
    swatch(key) { return `background:${this.state.colors[key] || "#ccc"}`; }
    layerLabel(el) { return el.name; }

    // ------------------------------------------------------------------ loading

    async load(keepSelection = true) {
        const data = await this.orm.call("mi.design", "editor_data", [[this.designId]]);
        Object.assign(this.state, {
            loaded: true, width: data.width, height: data.height, label: data.label, colors: data.colors,
            elements: data.elements, stamp: Date.now(),
        });
        if (!keepSelection || !this.selected) {
            this.state.selectedId = null;
        }
    }
    refresh() { this.state.stamp = Date.now(); }

    // ------------------------------------------------------------------ writing, with a history for Undo / Redo

    async writeElement(el, values, remember = true) {
        const before = {};
        for (const key of Object.keys(values)) {
            before[key] = el[key];
        }
        Object.assign(el, values);
        await this.orm.write(MODEL, [el.id], values);
        if (remember) {
            this.remember([{ type: "write", id: el.id, before, after: values }]);
        }
        this.refresh();
    }
    remember(ops) {
        this.state.past.push(ops);
        this.state.future.length = 0;
    }
    remap(oldId, newId) {
        for (const list of [this.state.past, this.state.future]) {
            for (const ops of list) {
                for (const op of ops) {
                    if (op.id === oldId) {
                        op.id = newId;
                    }
                }
            }
        }
        if (this.state.selectedId === oldId) {
            this.state.selectedId = newId;
        }
    }
    async createElement(values, remember = true) {
        const vals = { design_id: this.designId, ...values };
        const [id] = await this.orm.create(MODEL, [vals]);
        const [record] = await this.orm.read(MODEL, [id], [...SAVED, "name"]);
        this.state.elements.push(record);
        this.state.selectedId = id;
        if (remember) {
            this.remember([{ type: "create", id, vals: { ...values } }]);
        }
        this.refresh();
        return record;
    }
    async deleteElement(el, remember = true) {
        const [full] = await this.orm.read(MODEL, [el.id], [...SAVED, "image"]);
        await this.orm.unlink(MODEL, [el.id]);
        this.state.elements = this.state.elements.filter((other) => other.id !== el.id);
        if (this.state.selectedId === el.id) {
            this.state.selectedId = null;
        }
        if (remember) {
            const { id, ...vals } = full;
            this.remember([{ type: "delete", id: el.id, vals }]);
        }
        this.refresh();
    }
    async recreate(op) {
        const [id] = await this.orm.create(MODEL, [{ ...op.vals, design_id: this.designId }]);
        const [record] = await this.orm.read(MODEL, [id], [...SAVED, "name"]);
        this.state.elements.push(record);
        this.remap(op.id, id);
    }
    async undo() {
        const ops = this.state.past.pop();
        if (!ops) {
            return;
        }
        for (const op of [...ops].reverse()) {
            await this.apply(op, "undo");
        }
        this.state.future.push(ops);
        await this.load();
    }
    async redo() {
        const ops = this.state.future.pop();
        if (!ops) {
            return;
        }
        for (const op of ops) {
            await this.apply(op, "redo");
        }
        this.state.past.push(ops);
        await this.load();
    }
    async apply(op, way) {
        const el = this.state.elements.find((other) => other.id === op.id);
        if (op.type === "write" && el) {
            await this.orm.write(MODEL, [op.id], way === "undo" ? op.before : op.after);
        } else if ((op.type === "create" && way === "undo") || (op.type === "delete" && way === "redo")) {
            if (el) {
                await this.orm.unlink(MODEL, [op.id]);
            }
        } else if ((op.type === "create" && way === "redo") || (op.type === "delete" && way === "undo")) {
            await this.recreate(op);
        }
    }

    // ------------------------------------------------------------------ adding

    nextSequence() { return Math.max(0, ...this.state.elements.map((el) => el.sequence)) + 10; }
    place(width, height) {
        return {
            x: Math.round((this.state.width - width) / 2), y: Math.round((this.state.height - height) / 2),
            w: width, h: height, sequence: this.nextSequence(),
        };
    }
    addText() {
        const size = Math.round(this.state.width / 18);
        return this.createElement({
            kind: "text", text: _t("Your text"), size, font: "heading", bold: true, color: "dark",
            ...this.place(Math.round(this.state.width * 0.6), Math.round(size * 1.6)),
        });
    }
    addShape(shape) {
        const side = Math.round(Math.min(this.state.width, this.state.height) / 4);
        return this.createElement({ kind: "shape", shape, color: "accent", ...this.place(side, shape === "rect" ? side : Math.round(side * 0.6)) });
    }
    addLogo() {
        const width = Math.round(this.state.width / 5);
        return this.createElement({ kind: "logo", ...this.place(width, Math.round(width / 3)) });
    }
    addPictureElement() {
        const side = Math.round(Math.min(this.state.width, this.state.height) / 2);
        return this.createElement({ kind: "picture", ...this.place(side, side) });
    }
    uploadPicture(ev) {
        const file = ev.target.files[0];
        ev.target.value = "";
        if (!file) {
            return;
        }
        const reader = new FileReader();
        reader.onload = async () => {
            const image = String(reader.result).split(",")[1];
            const target = this.selected?.kind === "picture" && this.replacing ? this.selected : null;
            this.replacing = false;
            if (target) {
                await this.orm.write(MODEL, [target.id], { image });
                this.refresh();
            } else {
                await this.createElement({ ...(await this.pictureValues()), image });
            }
        };
        reader.readAsDataURL(file);
    }
    pictureValues() {
        const side = Math.round(Math.min(this.state.width, this.state.height) / 2);
        return { kind: "picture", ...this.place(side, side) };
    }
    pickUpload(replacing) {
        this.replacing = replacing;
        this.fileRef()?.click();
    }
    async pictureAction(method, replacing) {
        const target = replacing && this.selected?.kind === "picture" ? this.selected : await this.addPictureElement();
        this.action.doAction(
            await this.orm.call("mi.design", method, [[this.designId], target.id]),
            { onClose: () => this.load() }
        );
    }
    fromLibrary(replacing) { return this.pictureAction("action_pick_library_element", replacing); }
    aiImage(replacing) { return this.pictureAction("action_ai_image_element", replacing); }

    // ------------------------------------------------------------------ the panels

    select(el) { this.state.selectedId = el.id; }
    deselect() { this.state.selectedId = null; }
    setZoom(ev) { this.state.zoom = ev.target.value; }
    onValue(name, ev) {
        const el = this.selected;
        if (!el || el.locked) {
            return;
        }
        let value = ev.target.value;
        if (["x", "y", "w", "h", "size"].includes(name)) {
            value = Math.round(Number(value));
            if (Number.isNaN(value)) {
                return;
            }
            if (name === "w" || name === "h") {
                value = Math.max(value, MIN_SIDE);
            }
        }
        return this.writeElement(el, { [name]: value }).then(() => this.load());
    }
    setValue(name, value) {
        const el = this.selected;
        if (el && !el.locked) {
            return this.writeElement(el, { [name]: value }).then(() => this.load());
        }
    }
    toggle(el, name) { return this.writeElement(el, { [name]: !el[name] }).then(() => this.load()); }
    async duplicate() {
        const el = this.selected;
        if (!el) {
            return;
        }
        const [full] = await this.orm.read(MODEL, [el.id], [...SAVED, "image"]);
        const { id, ...vals } = full;
        await this.createElement({ ...vals, x: el.x + 40, y: el.y + 40, locked: false, sequence: this.nextSequence() });
    }
    async bringForward() {
        const el = this.selected;
        if (el) {
            await this.writeElement(el, { sequence: this.nextSequence() });
            await this.load();
        }
    }
    remove() {
        const el = this.selected;
        return el && !el.locked ? this.deleteElement(el) : undefined;
    }

    // ------------------------------------------------------------------ layers: drag to move up or down

    layerDragStart(el, ev) {
        this.state.dragLayer = el.id;
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", String(el.id));
    }
    layerDragOver(ev) { ev.preventDefault(); }
    async layerDrop(target, ev) {
        ev.preventDefault();
        const from = this.state.elements.find((el) => el.id === this.state.dragLayer);
        this.state.dragLayer = null;
        if (!from || from.id === target.id) {
            return;
        }
        // the dragged layer takes the place just above the one it was dropped on
        const order = this.layers.filter((el) => el.id !== from.id);
        const index = order.findIndex((el) => el.id === target.id);
        order.splice(index, 0, from);
        const ops = [];
        const top = order.length;
        for (const [position, el] of order.entries()) {
            const sequence = (top - position) * 10;
            if (el.sequence !== sequence) {
                ops.push({ type: "write", id: el.id, before: { sequence: el.sequence }, after: { sequence } });
                await this.orm.write(MODEL, [el.id], { sequence });
            }
        }
        if (ops.length) {
            this.remember(ops);
        }
        await this.load();
    }

    // ------------------------------------------------------------------ moving and resizing on the canvas

    startDrag(el, mode, ev) {
        ev.preventDefault();
        ev.stopPropagation();
        this.state.selectedId = el.id;
        if (el.locked) {
            return;
        }
        this.drag = {
            el, mode, startX: ev.clientX, startY: ev.clientY, from: { x: el.x, y: el.y, w: el.w, h: el.h }, moved: false,
        };
        window.addEventListener("pointermove", this.onMove);
        window.addEventListener("pointerup", this.onUp);
    }
    dragMove(ev) {
        const drag = this.drag;
        if (!drag) {
            return;
        }
        const dx = Math.round((ev.clientX - drag.startX) / this.scale);
        const dy = Math.round((ev.clientY - drag.startY) / this.scale);
        const { x, y, w, h } = drag.from;
        const el = drag.el;
        drag.moved = drag.moved || dx !== 0 || dy !== 0;
        if (drag.mode === "move") {
            Object.assign(el, { x: x + dx, y: y + dy });
            return;
        }
        let [nx, ny, nw, nh] = [x, y, w, h];
        if (drag.mode.includes("e")) {
            nw = Math.max(w + dx, MIN_SIDE);
        }
        if (drag.mode.includes("s")) {
            nh = Math.max(h + dy, MIN_SIDE);
        }
        if (drag.mode.includes("w")) {
            nw = Math.max(w - dx, MIN_SIDE);
            nx = x + w - nw;
        }
        if (drag.mode.includes("n")) {
            nh = Math.max(h - dy, MIN_SIDE);
            ny = y + h - nh;
        }
        Object.assign(el, { x: nx, y: ny, w: nw, h: nh });
    }
    async dragEnd() {
        const drag = this.drag;
        this.stopDrag();
        if (!drag || !drag.moved) {
            return;
        }
        const { el, from } = drag;
        const after = { x: el.x, y: el.y, w: el.w, h: el.h };
        await this.orm.write(MODEL, [el.id], after);
        this.remember([{ type: "write", id: el.id, before: from, after }]);
        this.refresh();
    }
    stopDrag() {
        this.drag = null;
        window.removeEventListener("pointermove", this.onMove);
        window.removeEventListener("pointerup", this.onUp);
    }
}

registry.category("view_widgets").add("mi_design_editor", { component: DesignEditor });
