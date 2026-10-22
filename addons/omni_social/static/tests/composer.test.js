import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { proxy } from "@odoo/owl";
import { contains, mountWithCleanup } from "@web/../tests/web_test_helpers";

import {
    SocialChoiceCards, SocialMediaDrop, SocialPreview, countChars, formatBytes, formatDuration, live, mediaItems,
} from "@omni_social/composer/composer";

defineMailModels();

const UI = {
    ready: true,
    platform: { code: "instagram", label: "Instagram", icon: "oi_instagram" },
    account: { name: "Metric", profile: "metric.io", kind: "organization" },
    operations: [
        { value: "post", label: "Post", description: "A new post on the account" },
        { value: "reply", label: "Public reply", description: "Answer in public" },
    ],
    formats: [
        { value: "standard", label: "Post", description: "One photo with a caption" },
        { value: "carousel", label: "Carousel", description: "2–10 photos" },
    ],
    text: { limit: 20, hidden: false, placeholder: "What do you want to say on Instagram?" },
    title: { limit: 0, hint: "" },
    media: {
        min: 1, max: 2, kinds: ["image"], accept: "image/jpeg", photo_bytes: 8 * 1024 * 1024,
        photo_pixels: 24000000, video_bytes: 64 * 1024 * 1024, video_seconds: [3, 900], video_width: 1920,
        rules: ["1 to 2 files", "Photos: JPEG"],
    },
    target: false,
};

function makeList(records = []) {
    const list = proxy({
        records,
        async addNewRecord() {
            const record = proxy({ id: `virtual_${list.records.length + 1}`, resId: false, data: {} });
            record.update = async (values) => Object.assign(record.data, values);
            list.records.push(record);
            return record;
        },
        async delete(record) {
            list.records.splice(list.records.indexOf(record), 1);
        },
    });
    return list;
}

function makeRecord(data = {}) {
    const record = {
        id: "datapoint_1",
        resId: 5,
        fields: { operation: { selection: [["post", "Post"]] }, format: { selection: [["standard", "Post"]] } },
        data: proxy({
            composer_ui: UI, operation: "post", format: "standard", body: "", name: "Spring",
            media_ids: makeList(), ...data,
        }),
        update: async (values) => {
            expect.step(`update:${Object.entries(values).map(([k, v]) => `${k}=${v}`).join(",")}`);
            Object.assign(record.data, values);
        },
    };
    return record;
}

test("helpers count and format like the server", () => {
    expect(countChars("héllo 👋")).toBe(7);
    expect(formatBytes(2.5 * 1024 * 1024)).toBe("2.5 MB");
    expect(formatBytes(4000)).toBe("4 KB");
    expect(formatDuration(75)).toBe("1:15");
});

test("choice cards show the account's options and select one", async () => {
    const record = makeRecord();
    await mountWithCleanup(SocialChoiceCards, { props: { id: "op", name: "operation", record, readonly: false } });
    expect(".o_social_choice").toHaveCount(2);
    expect(".o_social_choice.o_selected").toHaveText(/Post/);
    expect(".o_social_art").toHaveCount(2);
    await contains(".o_social_choice[data-value=reply] input").click();
    expect.verifySteps(["update:operation=reply"]);
    expect(".o_social_choice.o_selected").toHaveText(/Public reply/);
});

test("read-only choice cards show only the chosen option", async () => {
    await mountWithCleanup(SocialChoiceCards, {
        props: { id: "fmt", name: "format", record: makeRecord({ format: "carousel" }), readonly: true },
    });
    expect(".o_social_choice").toHaveCount(1);
    expect(".o_social_choice").toHaveText(/Carousel/);
});

test("drop zone takes allowed photos and explains refusals", async () => {
    const record = makeRecord();
    const component = await mountWithCleanup(SocialMediaDrop, {
        props: { id: "media", name: "media_ids", record, readonly: false },
    });
    expect(".o_social_rules li").toHaveCount(2);
    component.prepare = async (file) =>
        file.type === "video/mp4"
            ? { error: `${file.name}: this account takes photos here.` }
            : { kind: "image", blob: file, name: file.name, size: file.size, width: 10, height: 10 };
    const photo = (name) => new File(["x"], name, { type: "image/jpeg" });
    await component.addFiles([photo("a.jpg"), new File(["v"], "v.mp4", { type: "video/mp4" }), photo("b.jpg"), photo("c.jpg")]);
    await animationFrame();
    expect(".o_social_thumb").toHaveCount(2);
    expect(".o_social_media_errors div").toHaveCount(2);
    expect(".o_social_media_errors").toHaveText(/v\.mp4: this account takes photos here\./);
    expect(".o_social_media_errors").toHaveText(/c\.jpg: this post takes up to 2 files\./);
    expect(record.data.media_ids.records.map((r) => r.data.sequence)).toEqual([1, 2]);
    expect(".o_social_thumb:first-child .o_social_thumb_info").toHaveText(/a\.jpg/);
    await contains(".o_social_thumb:first-child .o_social_remove").click();
    expect(".o_social_thumb").toHaveCount(1);
});

test("files that the format does not take are flagged", async () => {
    const list = makeList();
    const record = makeRecord({ media_ids: list });
    const video = await list.addNewRecord();
    await video.update({ kind: "video", name: "clip.mp4", sequence: 1 });
    await mountWithCleanup(SocialMediaDrop, { props: { id: "media", name: "media_ids", record, readonly: false } });
    expect(".o_social_thumb.o_problem").toHaveCount(1);
    expect(".o_social_problem").toHaveText(/Instagram takes photos only here/);
    expect(mediaItems(record).filter((i) => !i.problem)).toHaveLength(0);
});

test("preview follows the platform and the typed text", async () => {
    const record = makeRecord({ body: "Autumn is here and the new release is out today" });
    await mountWithCleanup(SocialPreview, { props: { record, readonly: false } });
    expect(".o_pv_instagram").toHaveCount(1);
    expect(".o_pv_body").toHaveText(/metric\.io/);
    expect(".o_pv_more_link").toHaveCount(0);
    expect(".alert-danger").toHaveCount(1); // 47 characters, the limit here is 20
    live.text[`${record.id}:body`] = "Short";
    await animationFrame();
    expect(".o_pv_body").toHaveText(/Short/);
    expect(".alert-danger").toHaveCount(0);
    delete live.text[`${record.id}:body`];
    record.data.composer_ui = { ...UI, platform: { code: "x", label: "X", icon: "oi_x" } };
    await animationFrame();
    expect(".o_pv_x .o_pv_side").toHaveCount(1);
    record.data.operation = "reply";
    record.data.composer_ui = { ...UI, target: { author: "Ann", body: "Will it be recorded?", kind: "comment" } };
    await animationFrame();
    expect(".o_pv_thread .o_pv_comment").toHaveCount(2);
    expect(".o_pv_thread").toHaveText(/Will it be recorded\?/);
});

test("preview waits for an account", async () => {
    await mountWithCleanup(SocialPreview, {
        props: { record: makeRecord({ composer_ui: { ready: false } }), readonly: false },
    });
    expect(".o_social_preview_empty").toHaveCount(1);
});
