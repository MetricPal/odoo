import { Component, onWillStart, proxy, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { deserializeDate, deserializeDateTime, serializeDate, serializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { CogMenu } from "@web/search/cog_menu/cog_menu";
import { Layout } from "@web/search/layout";
import { SearchBar } from "@web/search/search_bar/search_bar";
import { standardViewProps } from "@web/views/standard_view_props";

const { DateTime } = luxon;

export const SCALES = {
    day: { label: _t("Day"), unit: "hour", columns: 24, span: { days: 1 } },
    week: { label: _t("Week"), unit: "day", columns: 7, span: { weeks: 1 } },
    month: { label: _t("Month"), unit: "day", columns: null, span: { months: 1 } },
    year: { label: _t("Year"), unit: "month", columns: 12, span: { years: 1 } },
};
const COLORS = ["#8e7cc3", "#4f7fbf", "#2e8b6e", "#b08d2d", "#c0605a", "#5b8fa8", "#8a6d3b", "#6c757d",
    "#a0628a", "#4c9a8d", "#7d7fbf", "#b0703c"];

/** Reads the <gantt> arch. */
export function parseGanttArch(arch) {
    const get = (name) => arch.getAttribute(name) || false;
    return {
        dateStart: get("date_start"),
        dateStop: get("date_stop"),
        color: get("color"),
        progress: get("progress"),
        dependencyField: get("dependency_field"),
        defaultGroupBy: (get("default_group_by") || "").split(",").filter(Boolean),
        defaultScale: get("default_scale") || "week",
        create: get("create") !== "0",
        edit: get("edit") !== "0",
        title: get("string") || "",
        fieldNames: [...arch.querySelectorAll("field")].map((node) => node.getAttribute("name")),
    };
}

/** Where a date falls in the visible range, as a percentage (clamped). */
export function position(value, start, end) {
    const total = end.toMillis() - start.toMillis();
    const pct = ((value.toMillis() - start.toMillis()) / total) * 100;
    return Math.max(0, Math.min(100, pct));
}

export class GanttController extends Component {
    static template = "gantt_view.GanttController";
    static components = { Layout, SearchBar, CogMenu };

    props = useProps({ ...standardViewProps });

    setup() {
        this.orm = useService("orm");
        this.archInfo = parseGanttArch(this.props.arch);
        this.state = proxy({
            scale: this.archInfo.defaultScale,
            anchor: DateTime.local().startOf("day"),
            rows: [],
            unplanned: 0,
            loading: true,
            drag: null,
        });
        useBus(this.env.searchModel, "update", () => this.load());
        onWillStart(() => this.load());
    }

    // ------------------------------------------------------------------ range

    get range() {
        const scale = SCALES[this.state.scale];
        const unit = { day: "day", week: "week", month: "month", year: "year" }[this.state.scale];
        const start = this.state.anchor.startOf(unit);
        return { start, end: start.plus(scale.span) };
    }

    get columns() {
        const { start, end } = this.range;
        const scale = SCALES[this.state.scale];
        const cols = [];
        let cursor = start;
        while (cursor < end) {
            const next = cursor.plus({ [scale.unit + "s"]: 1 });
            cols.push({
                key: cursor.toISO(),
                label: scale.unit === "hour" ? cursor.toFormat("HH") : scale.unit === "day"
                    ? cursor.toFormat(this.state.scale === "week" ? "ccc d" : "d") : cursor.toFormat("MMM"),
                today: scale.unit !== "hour" && cursor.hasSame(DateTime.local(), scale.unit),
            });
            cursor = next;
        }
        return cols;
    }

    get title() {
        const { start, end } = this.range;
        switch (this.state.scale) {
            case "day": return start.toFormat("cccc d LLLL yyyy");
            case "week": return `${start.toFormat("d LLL")} – ${end.minus({ days: 1 }).toFormat("d LLL yyyy")}`;
            case "month": return start.toFormat("LLLL yyyy");
            default: return start.toFormat("yyyy");
        }
    }

    get todayPosition() {
        const { start, end } = this.range;
        const now = DateTime.local();
        return now >= start && now < end ? position(now, start, end) : null;
    }

    // ------------------------------------------------------------------ data

    parse(fieldName, value) {
        if (!value) {
            return null;
        }
        const type = this.props.fields[fieldName]?.type;
        return type === "date" ? deserializeDate(value) : deserializeDateTime(value);
    }

    serialize(fieldName, value) {
        const type = this.props.fields[fieldName]?.type;
        return type === "date" ? serializeDate(value) : serializeDateTime(value);
    }

    get groupBy() {
        const fromSearch = (this.env.searchModel?.groupBy || []).map((g) => g.split(":")[0]);
        return (fromSearch.length ? fromSearch : this.archInfo.defaultGroupBy).slice(0, 1);
    }

    async load() {
        const { dateStart, dateStop, color, progress, dependencyField } = this.archInfo;
        const { start, end } = this.range;
        const groupField = this.groupBy[0];
        const names = new Set(["display_name", dateStart, dateStop, ...this.archInfo.fieldNames]);
        for (const name of [color, progress, dependencyField, groupField]) {
            if (name) {
                names.add(name);
            }
        }
        const domain = [
            ...(this.env.searchModel?.domain || this.props.domain || []),
            "|", [dateStart, "!=", false], [dateStop, "!=", false],
        ];
        const records = await this.orm.searchRead(this.props.resModel, domain, [...names],
            { context: this.props.context, limit: 2000 });
        const groupFieldInfo = groupField && this.props.fields[groupField];
        if (groupFieldInfo?.type === "many2many") {
            const ids = [...new Set(records.flatMap((r) => r[groupField] || []))];
            const named = ids.length ? await this.orm.read(groupFieldInfo.relation, ids, ["display_name"]) : [];
            this.m2mNames = Object.fromEntries(named.map((n) => [`${groupField}-${n.id}`, n.display_name]));
        }
        const groups = new Map();
        let unplanned = 0;
        for (const record of records) {
            let stop = this.parse(dateStop, record[dateStop]);
            let begin = this.parse(dateStart, record[dateStart]);
            if (!begin && !stop) {
                unplanned++;
                continue;
            }
            begin = begin || stop.minus({ days: 1 });
            stop = stop || begin.plus({ days: 1 });
            if (stop <= begin) {
                stop = begin.plus({ hours: 1 });
            }
            if (this.props.fields[dateStop]?.type === "date") {
                stop = stop.plus({ days: 1 });  // a date ends at the end of its day
            }
            if (stop <= start || begin >= end) {
                continue;
            }
            const bar = {
                id: record.id,
                name: record.display_name,
                begin, stop,
                left: position(begin, start, end),
                width: Math.max(position(stop, start, end) - position(begin, start, end), 0.8),
                color: COLORS[(color && Number.isInteger(record[color]) ? record[color] : 0) % COLORS.length],
                progress: progress ? Math.round(record[progress] || 0) : null,
                depends: dependencyField ? record[dependencyField] || [] : [],
                clippedLeft: begin < start,
                clippedRight: stop > end,
            };
            for (const key of this.groupKeys(record, groupField)) {
                if (!groups.has(key.id)) {
                    groups.set(key.id, { id: key.id, label: key.label, bars: [] });
                }
                groups.get(key.id).bars.push(bar);
            }
        }
        const rows = [];
        let index = 0;
        for (const group of [...groups.values()].sort((a, b) => String(a.label).localeCompare(String(b.label)))) {
            if (groupField) {
                rows.push({ type: "group", key: `g-${group.id}`, label: group.label, count: group.bars.length });
            }
            for (const bar of group.bars.sort((a, b) => a.begin - b.begin)) {
                rows.push({ type: "bar", key: `b-${group.id}-${bar.id}`, bar, index: index++ });
            }
        }
        this.state.rows = rows;
        this.state.unplanned = unplanned;
        this.state.loading = false;
    }

    groupKeys(record, groupField) {
        if (!groupField) {
            return [{ id: "all", label: "" }];
        }
        const value = record[groupField];
        const field = this.props.fields[groupField];
        if (field?.type === "many2many") {
            return value?.length ? value.map((id) => ({ id, label: this.m2mLabel(groupField, id) })) :
                [{ id: false, label: _t("None") }];
        }
        if (Array.isArray(value)) {
            return [{ id: value[0], label: value[1] }];
        }
        if (field?.type === "selection") {
            const option = field.selection.find((s) => s[0] === value);
            return [{ id: value || false, label: option ? option[1] : _t("None") }];
        }
        return [{ id: value ?? false, label: value || _t("None") }];
    }

    m2mLabel(fieldName, id) {
        this.m2mNames ||= {};
        return this.m2mNames[`${fieldName}-${id}`] || `#${id}`;
    }

    // ------------------------------------------------------------------ dependencies

    get arrows() {
        const rowOf = {};
        for (const row of this.state.rows) {
            if (row.type === "bar" && !(row.bar.id in rowOf)) {
                rowOf[row.bar.id] = row;
            }
        }
        const arrows = [];
        for (const row of this.state.rows) {
            if (row.type !== "bar") {
                continue;
            }
            for (const id of row.bar.depends) {
                const from = rowOf[id];
                if (from) {
                    arrows.push({ key: `${id}-${row.bar.id}`, x1: from.bar.left + from.bar.width,
                        y1: this.rowTop(from) + 17, x2: row.bar.left, y2: this.rowTop(row) + 17 });
                }
            }
        }
        return arrows;
    }

    rowTop(target) {
        let top = 0;
        for (const row of this.state.rows) {
            if (row === target) {
                return top;
            }
            top += row.type === "group" ? 30 : 36;
        }
        return top;
    }

    get bodyHeight() {
        return this.state.rows.reduce((h, row) => h + (row.type === "group" ? 30 : 36), 0);
    }

    // ------------------------------------------------------------------ navigation

    scaleLabel(scale) {
        return SCALES[scale].label;
    }

    setScale(scale) {
        this.state.scale = scale;
        this.load();
    }

    move(step) {
        this.state.anchor = step ? this.state.anchor.plus(
            Object.fromEntries(Object.entries(SCALES[this.state.scale].span).map(([k, v]) => [k, v * step]))
        ) : DateTime.local().startOf("day");
        this.load();
    }

    openRecord(bar) {
        if (this.state.drag?.moved) {
            return;
        }
        this.props.selectRecord?.(bar.id);
    }

    createRecord() {
        this.props.createRecord?.();
    }

    // ------------------------------------------------------------------ drag to move or resize

    startDrag(ev, bar, mode) {
        if (!this.archInfo.edit) {
            return;
        }
        ev.stopPropagation();
        const track = ev.currentTarget.closest(".o_gantt_track");
        this.state.drag = { bar, mode, x: ev.clientX, width: track.getBoundingClientRect().width,
            left: bar.left, barWidth: bar.width, moved: false };
        const onMove = (e) => this.onDrag(e);
        const onUp = async (e) => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
            await this.endDrag(e);
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    }

    onDrag(ev) {
        const drag = this.state.drag;
        if (!drag) {
            return;
        }
        const delta = ((ev.clientX - drag.x) / drag.width) * 100;
        if (Math.abs(ev.clientX - drag.x) > 3) {
            drag.moved = true;
        }
        if (drag.mode === "move") {
            drag.bar.left = drag.left + delta;
        } else {
            drag.bar.width = Math.max(drag.barWidth + delta, 0.8);
        }
    }

    async endDrag(ev) {
        const drag = this.state.drag;
        if (!drag || !drag.moved) {
            this.state.drag = null;
            return;
        }
        const { start, end } = this.range;
        const scale = SCALES[this.state.scale];
        const pxToMs = (end.toMillis() - start.toMillis()) / drag.width;
        let shift = (ev.clientX - drag.x) * pxToMs;
        // snap to the scale's unit (hour in day view, day otherwise)
        const snap = scale.unit === "hour" ? 3600e3 : 86400e3;
        shift = Math.round(shift / snap) * snap;
        const { dateStart, dateStop } = this.archInfo;
        const values = {};
        if (drag.mode === "move") {
            values[dateStart] = this.serialize(dateStart, drag.bar.begin.plus({ milliseconds: shift }));
        }
        let stop = drag.bar.stop.plus({ milliseconds: shift });
        if (this.props.fields[dateStop]?.type === "date") {
            stop = stop.minus({ days: 1 });
        }
        values[dateStop] = this.serialize(dateStop, stop);
        try {
            await this.orm.write(this.props.resModel, [drag.bar.id], values, { context: this.props.context });
        } finally {
            setTimeout(() => (this.state.drag = null), 0);
            await this.load();
        }
    }
}

export const ganttView = {
    type: "gantt",
    display_name: _t("Gantt"),
    icon: "view_timeline",
    multiRecord: true,
    searchMenuTypes: ["filter", "groupBy", "favorite"],
    Controller: GanttController,
    props: (genericProps) => genericProps,
};

registry.category("views").add("gantt", ganttView);
