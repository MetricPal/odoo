import { Component, onWillUnmount, proxy, signal, t, useProps } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { getFieldDomain } from "@web/model/relational_model/utils";
import { useSpecialData } from "@web/views/fields/relational_utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { TextField, textField } from "@web/views/fields/text/text_field";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * Post editor for omni.social.publication.
 *
 * The record's `composer_ui` (computed from the connector's declared
 * capabilities) drives every widget: which actions and formats the account
 * offers, the character and file limits, placeholders, and the preview data.
 * The server checks the same rules again when the post is submitted.
 */

// Text being typed and files dropped but not saved yet, shared with the preview.
export const live = proxy({ text: {}, files: {} });

const textKey = (record, name) => `${record.id}:${name}`;

export function composerUi(record) {
    return record.data.composer_ui || {};
}

export function countChars(value) {
    return [...(value || "")].length; // code points, as the server counts
}

export function formatBytes(bytes) {
    if (!bytes) {
        return "";
    }
    if (bytes < 1024 * 1024) {
        return `${Math.max(1, Math.round(bytes / 1024))} KB`;
    }
    return `${(bytes / (1024 * 1024)).toFixed(1).replace(/\.0$/, "")} MB`;
}

export function formatDuration(seconds) {
    if (!seconds) {
        return "";
    }
    const total = Math.round(seconds);
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

// ---------------------------------------------------------------- accounts

export class SocialAccountCards extends Component {
    static template = "omni_social.AccountCards";
    props = useProps({ ...standardFieldProps, domain: t.or([t.array(), t.function()]).optional() });

    setup() {
        this.state = proxy({ filter: "" });
        this.accounts = useSpecialData(async (orm, props) => {
            const domain = getFieldDomain(props.record, props.name, props.domain) || [];
            const { records } = await orm.call("omni.social.connection", "web_search_read", [], {
                domain: [...domain, ["connected", "=", true], ["active", "=", true]],
                specification: { display_name: 1, provider: 1, profile_name: 1 },
                limit: 80,
            });
            return records;
        });
    }
    get value() {
        return this.props.record.data[this.props.name];
    }
    get items() {
        const all = this.accounts.data.length ? this.accounts.data : [];
        const filter = this.state.filter.trim().toLowerCase();
        const items = filter
            ? all.filter((a) => `${a.display_name} ${a.profile_name || ""} ${a.provider}`.toLowerCase().includes(filter))
            : all;
        if (this.props.readonly) {
            return items.filter((a) => a.id === this.value?.id);
        }
        return items;
    }
    icon(provider) {
        return ICONS[provider] || "public";
    }
    select(account) {
        if (this.props.readonly || account.id === this.value?.id) {
            return;
        }
        this.props.record.update({ [this.props.name]: { id: account.id, display_name: account.display_name } });
    }
}

const ICONS = {
    instagram: "oi_instagram", facebook: "oi_facebook", linkedin: "oi_linkedin", x: "oi_x",
    threads: "oi_threads", tiktok: "oi_tiktok", youtube: "oi_youtube-play", pinterest: "oi_pinterest",
    discord: "oi_discord",
};

registry.category("fields").add("social_account_cards", {
    component: SocialAccountCards,
    supportedTypes: ["many2one"],
    extractProps: (fieldInfo, dynamicInfo) => ({ domain: dynamicInfo.domain }),
});

// ---------------------------------------------------------------- choices

export class SocialChoiceCards extends Component {
    static template = "omni_social.ChoiceCards";
    props = useProps({ ...standardFieldProps });

    get value() {
        return this.props.record.data[this.props.name];
    }
    get options() {
        const ui = composerUi(this.props.record);
        const declared = this.props.name === "operation" ? ui.operations : ui.formats;
        if (declared && declared.length) {
            return declared;
        }
        return (this.props.record.fields[this.props.name].selection || []).map(([value, label]) => ({
            value, label, description: "",
        }));
    }
    get visibleOptions() {
        return this.props.readonly ? this.options.filter((o) => o.value === this.value) : this.options;
    }
    select(value) {
        if (!this.props.readonly && value !== this.value) {
            this.props.record.update({ [this.props.name]: value });
        }
    }
}

registry.category("fields").add("social_choice_cards", {
    component: SocialChoiceCards,
    supportedTypes: ["selection"],
});

// ---------------------------------------------------------------- text with counter

export class SocialTextField extends TextField {
    static template = "omni_social.TextField";

    get ui() {
        return composerUi(this.props.record);
    }
    get placeholderText() {
        return this.ui.text?.placeholder || this.props.placeholder || "";
    }
    get liveValue() {
        const typed = live.text[textKey(this.props.record, this.props.name)];
        return typed ?? this.value;
    }
    get limit() {
        return this.ui.text?.limit || 0;
    }
    get count() {
        return countChars(this.liveValue);
    }
    get over() {
        return this.limit && this.count > this.limit;
    }
    onTyping(ev) {
        live.text[textKey(this.props.record, this.props.name)] = ev.target.value;
    }
    onBlur() {
        super.onBlur();
        delete live.text[textKey(this.props.record, this.props.name)];
    }
}

registry.category("fields").add("social_text", { ...textField, component: SocialTextField });

// ---------------------------------------------------------------- title hint

export class SocialTitleHint extends Component {
    static template = "omni_social.TitleHint";
    props = useProps(standardWidgetProps);
    get title() {
        return composerUi(this.props.record).title || {};
    }
    get count() {
        return countChars(this.props.record.data.name);
    }
}

registry.category("view_widgets").add("social_title_hint", { component: SocialTitleHint });

// ---------------------------------------------------------------- media

/** Reads a dropped photo, converts it to JPEG when needed and fits it in the pixel limit. */
async function preparePhoto(file, rules) {
    const url = URL.createObjectURL(file);
    try {
        const img = await new Promise((resolve, reject) => {
            const image = new Image();
            image.onload = () => resolve(image);
            image.onerror = () => reject(new Error("decode"));
            image.src = url;
        });
        let { naturalWidth: width, naturalHeight: height } = img;
        const pixels = width * height;
        const tooBig = pixels > rules.photo_pixels;
        if (file.type === "image/jpeg" && !tooBig && file.size <= rules.photo_bytes) {
            return { blob: file, width, height, name: file.name };
        }
        if (tooBig) {
            const scale = Math.sqrt(rules.photo_pixels / pixels) * 0.98;
            width = Math.floor(width * scale);
            height = Math.floor(height * scale);
        }
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff"; // transparent PNG areas become white, not black
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(img, 0, 0, width, height);
        let blob = null;
        for (const quality of [0.92, 0.85, 0.75, 0.6]) {
            blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
            if (blob && blob.size <= rules.photo_bytes) {
                break;
            }
        }
        return { blob, width, height, name: file.name.replace(/\.[^.]+$/, "") + ".jpg", converted: true };
    } finally {
        URL.revokeObjectURL(url);
    }
}

async function readVideo(file) {
    const url = URL.createObjectURL(file);
    try {
        return await new Promise((resolve, reject) => {
            const video = document.createElement("video");
            video.preload = "metadata";
            video.onloadedmetadata = () =>
                resolve({ width: video.videoWidth, height: video.videoHeight, duration: video.duration });
            video.onerror = () => reject(new Error("decode"));
            video.src = url;
        });
    } finally {
        URL.revokeObjectURL(url);
    }
}

function toBase64(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1]);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });
}

export function mediaItems(record, name = "media_ids") {
    const list = record.data[name];
    const records = list?.records ? [...list.records] : [];
    const rules = composerUi(record).media || {};
    const label = composerUi(record).platform?.label || "";
    const items = records
        .sort((a, b) => (a.data.sequence || 0) - (b.data.sequence || 0) || String(a.id).localeCompare(String(b.id)))
        .map((rec) => {
            const local = live.files[rec.id] || {};
            const saved = rec.resId && !local.url;
            const kind = rec.data.kind || local.kind || "image";
            return {
                record: rec,
                id: rec.id,
                kind,
                name: rec.data.name || local.name || "",
                url: local.url || (saved
                    ? `/web/${kind === "video" ? "content" : "image"}/omni.social.media/${rec.resId}/file`
                    : ""),
                width: local.width || rec.data.width || 0,
                height: local.height || rec.data.height || 0,
                duration: local.duration || rec.data.duration || 0,
                size: local.size || rec.data.file_size || 0,
                converted: local.converted || false,
            };
        });
    // Files that this account or format does not take stay listed with the reason.
    let accepted = 0;
    for (const item of items) {
        item.problem = "";
        if (rules.kinds && !rules.kinds.includes(item.kind)) {
            item.problem = item.kind === "video"
                ? _t("%(platform)s takes photos only here", { platform: label })
                : _t("%(platform)s takes a video here", { platform: label });
        } else if (rules.max !== undefined && accepted >= rules.max) {
            item.problem = _t("Over the limit of %(max)s", { max: rules.max });
        } else {
            accepted += 1;
        }
    }
    return items;
}

export class SocialMediaDrop extends Component {
    static template = "omni_social.MediaDrop";
    props = useProps({ ...standardFieldProps });

    setup() {
        this.notification = useService("notification");
        this.inputRef = signal.ref();
        this.state = proxy({ dragging: false, busy: false, errors: [] });
        this.urls = [];
        onWillUnmount(() => this.urls.forEach((url) => URL.revokeObjectURL(url)));
    }
    get rules() {
        return composerUi(this.props.record).media || { max: 0, rules: [] };
    }
    get items() {
        return mediaItems(this.props.record, this.props.name);
    }
    get full() {
        return this.items.length >= (this.rules.max || 0);
    }
    get problems() {
        return this.items.filter((i) => i.problem).length;
    }
    get fullLabel() {
        return this.rules.max === 1
            ? _t("This format takes one file. Remove it to use another.")
            : _t("This format takes up to %(max)s files. Remove one to add another.", { max: this.rules.max });
    }
    get kindsLabel() {
        const kinds = this.rules.kinds || [];
        if (kinds.length > 1) {
            return _t("photos or videos");
        }
        return kinds[0] === "video" ? _t("a video") : _t("photos");
    }
    dims(item) {
        return item.width && item.height ? `${item.width} × ${item.height}` : "";
    }
    size(item) {
        return formatBytes(item.size);
    }
    info(item) {
        return [this.dims(item), this.size(item)].filter(Boolean).join(" · ");
    }
    length(item) {
        return formatDuration(item.duration);
    }
    browse() {
        this.inputRef()?.click();
    }
    onDragOver(ev) {
        if (this.props.readonly) {
            return;
        }
        ev.preventDefault();
        this.state.dragging = true;
    }
    onDragLeave() {
        this.state.dragging = false;
    }
    async onDrop(ev) {
        ev.preventDefault();
        this.state.dragging = false;
        if (!this.props.readonly) {
            await this.addFiles([...(ev.dataTransfer?.files || [])]);
        }
    }
    async onPick(ev) {
        const files = [...(ev.target.files || [])];
        ev.target.value = "";
        await this.addFiles(files);
    }

    /** Check one file against the platform rules; returns the prepared upload or an error text. */
    async prepare(file) {
        const rules = this.rules;
        const kinds = rules.kinds || [];
        const kind = file.type.startsWith("video/") ? "video" : file.type.startsWith("image/") ? "image" : "";
        if (!kind || !kinds.includes(kind)) {
            return { error: _t("%(name)s: this account takes %(kinds)s here.", { name: file.name, kinds: this.kindsLabel }) };
        }
        if (kind === "image") {
            if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
                return { error: _t("%(name)s: use a JPEG, PNG or WebP photo.", { name: file.name }) };
            }
            let photo;
            try {
                photo = await preparePhoto(file, rules);
            } catch {
                return { error: _t("%(name)s: this photo could not be read.", { name: file.name }) };
            }
            if (!photo.blob || photo.blob.size > rules.photo_bytes) {
                return { error: _t("%(name)s: photos must be under %(size)s.", { name: file.name, size: formatBytes(rules.photo_bytes) }) };
            }
            return { kind, ...photo, size: photo.blob.size };
        }
        if (file.type !== "video/mp4") {
            return { error: _t("%(name)s: use an MP4 video.", { name: file.name }) };
        }
        if (file.size > rules.video_bytes) {
            return { error: _t("%(name)s: videos must be under %(size)s.", { name: file.name, size: formatBytes(rules.video_bytes) }) };
        }
        let meta;
        try {
            meta = await readVideo(file);
        } catch {
            return { error: _t("%(name)s: this video could not be read. Use H.264 or HEVC in MP4.", { name: file.name }) };
        }
        const [low, high] = rules.video_seconds || [3, 900];
        if (meta.duration < low || meta.duration > high) {
            return {
                error: _t("%(name)s: videos here must last %(low)s–%(high)s seconds (this one: %(length)s).", {
                    name: file.name, low, high, length: formatDuration(meta.duration),
                }),
            };
        }
        if (meta.width > rules.video_width) {
            return { error: _t("%(name)s: videos can be at most %(width)s px wide.", { name: file.name, width: rules.video_width }) };
        }
        return { kind, blob: file, name: file.name, size: file.size, ...meta };
    }

    async addFiles(files) {
        if (!files.length || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.errors = [];
        const errors = [];
        try {
            const list = this.props.record.data[this.props.name];
            let room = (this.rules.max || 0) - this.items.length;
            let sequence = Math.max(0, ...this.items.map((i) => i.record.data.sequence || 0));
            for (const file of files) {
                if (room <= 0) {
                    errors.push(_t("%(name)s: this post takes up to %(max)s files.", { name: file.name, max: this.rules.max }));
                    continue;
                }
                const prepared = await this.prepare(file);
                if (prepared.error) {
                    errors.push(prepared.error);
                    continue;
                }
                const data = await toBase64(prepared.blob);
                const record = await list.addNewRecord({ position: "bottom" });
                sequence += 1;
                await record.update({ name: prepared.name, kind: prepared.kind, file: data, sequence });
                const url = URL.createObjectURL(prepared.blob);
                this.urls.push(url);
                live.files[record.id] = {
                    url, kind: prepared.kind, name: prepared.name, size: prepared.size,
                    width: prepared.width, height: prepared.height, duration: prepared.duration,
                    converted: Boolean(prepared.converted),
                };
                room -= 1;
            }
        } finally {
            this.state.busy = false;
            this.state.errors = errors;
        }
    }
    async remove(item) {
        await this.props.record.data[this.props.name].delete(item.record);
        delete live.files[item.id];
    }
    async move(item, step) {
        const items = this.items;
        const index = items.findIndex((i) => i.id === item.id);
        const other = items[index + step];
        if (!other) {
            return;
        }
        // Distinct sequences first so the swap is stable.
        for (const [i, it] of items.entries()) {
            if (it.record.data.sequence !== i + 1) {
                await it.record.update({ sequence: i + 1 });
            }
        }
        await item.record.update({ sequence: index + 1 + step });
        await other.record.update({ sequence: index + 1 });
    }
}

registry.category("fields").add("social_media_drop", {
    component: SocialMediaDrop,
    supportedTypes: ["one2many"],
    relatedFields: [
        // Related fields are read-only (and not saved) unless marked otherwise.
        { name: "sequence", type: "integer", readonly: false },
        { name: "name", type: "char", readonly: false },
        { name: "kind", type: "selection", selection: [["image", "Photo"], ["video", "Video"]], readonly: false },
        { name: "file", type: "binary", readonly: false },
        { name: "width", type: "integer" },
        { name: "height", type: "integer" },
        { name: "duration", type: "float" },
        { name: "file_size", type: "integer" },
    ],
});

// ---------------------------------------------------------------- preview

const MORE_AFTER = { instagram: 125, facebook: 480, linkedin: 210, threads: 500, tiktok: 100, x: 280, youtube: 160, pinterest: 100 };

export class SocialPreview extends Component {
    static template = "omni_social.Preview";
    props = useProps(standardWidgetProps);

    setup() {
        this.state = proxy({ expanded: false, slide: 0 });
    }
    get ui() {
        return composerUi(this.props.record);
    }
    get data() {
        return this.props.record.data;
    }
    get platform() {
        return this.ui.platform?.code || "";
    }
    get operation() {
        return this.data.operation || "post";
    }
    get format() {
        return this.data.format || "standard";
    }
    get vertical() {
        return this.operation === "post" && (["reel", "story"].includes(this.format) || this.platform === "tiktok");
    }
    get text() {
        const typed = live.text[textKey(this.props.record, "body")];
        return typed ?? this.data.body ?? "";
    }
    get title() {
        return this.data.name || "";
    }
    get account() {
        return this.ui.account || {};
    }
    get handle() {
        const profile = this.account.profile || this.account.name || "";
        return profile.replace(/^@/, "");
    }
    get initial() {
        return (this.account.profile || this.account.name || "?").replace(/^@/, "").charAt(0).toUpperCase();
    }
    get media() {
        return this.operation === "post"
            ? mediaItems(this.props.record).filter((i) => i.url && !i.problem)
            : [];
    }
    get slide() {
        return this.media[Math.min(this.state.slide, Math.max(0, this.media.length - 1))];
    }
    get target() {
        return this.ui.target || null;
    }
    get when() {
        const at = this.data.scheduled_at;
        if (this.operation === "post" && at && at.toFormat) {
            return at.toFormat("d LLL, HH:mm");
        }
        return _t("Just now");
    }
    get short() {
        const limit = MORE_AFTER[this.platform] || 300;
        const chars = [...this.text];
        if (this.state.expanded || chars.length <= limit) {
            return { text: this.text, more: false };
        }
        return { text: chars.slice(0, limit).join("").trimEnd(), more: true };
    }
    get grid() {
        const media = this.media;
        return { shown: media.slice(0, 4), extra: Math.max(0, media.length - 4), count: Math.min(media.length, 4) };
    }
    get over() {
        return this.ui.text?.limit && countChars(this.text) > this.ui.text.limit;
    }
    expand() {
        this.state.expanded = true;
    }
    step(delta) {
        const count = this.media.length;
        if (count) {
            this.state.slide = (Math.min(this.state.slide, count - 1) + delta + count) % count;
        }
    }
}

registry.category("view_widgets").add("social_preview", { component: SocialPreview });
