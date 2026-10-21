import { defineMailModels } from "@mail/../tests/mail_test_helpers";
import { expect, test } from "@odoo/hoot";
import { animationFrame } from "@odoo/hoot-dom";
import { proxy } from "@odoo/owl";
import { contains, mockService, mountWithCleanup } from "@web/../tests/web_test_helpers";

import { SocialCredentials } from "@omni_social/credentials";

// The web client services started by the test helpers talk to Discuss.
defineMailModels();

function makeRecord(ui, data = {}) {
    const record = {
        resId: 7,
        data: proxy({ provider: "linkedin", account_kind: "person", connected: false, credentials_ui: ui, ...data }),
        saved: true,
        save: async () => record.saved,
        model: { load: async () => expect.step("reload") },
    };
    return record;
}

async function mount(record) {
    return mountWithCleanup(SocialCredentials, {
        props: { id: "social", name: "credentials_ui", record, readonly: false },
    });
}

const SIGN_IN = { installed: true, label: "LinkedIn", oauth: true, oauth_app: true, app_id: "app-1", public_url: true };

test("token path connects and clears the token", async () => {
    mockService("orm", { call: async (model, method, args) => expect.step(`${method}:${args[1]}`) });
    const component = await mount(makeRecord({ installed: true, label: "Demo", oauth: false }));
    expect(".o_social_sign_in").toHaveCount(0);
    await contains("input[type=password]").edit("secret-token");
    await contains(".o_social_connect").click();
    expect.verifySteps(["action_connect:secret-token", "reload"]);
    expect(component.state.token).toBe("");
});

test("sign-in asks for the developer app once", async () => {
    mockService("orm", { call: async (model, method, args) => expect.step(`${method}:${args[1]}:${args[2]}`) });
    const component = await mount(makeRecord({ ...SIGN_IN, oauth_app: false }));
    expect(".o_social_sign_in").toHaveCount(0);
    await contains("#social_app_id").edit("client");
    await contains("#social_app_secret").edit("very-secret");
    await contains(".o_social_save_app").click();
    expect.verifySteps(["action_oauth_app:client:very-secret", "reload"]);
    expect(component.state.appSecret).toBe("");
});

test("sign-in opens the platform page", async () => {
    mockService("orm", {
        call: async (model, method) => {
            expect.step(method);
            return { type: "ir.actions.act_url", url: "https://platform.example/authorize" };
        },
    });
    mockService("action", { doAction: async (action) => expect.step(`open ${action.url}`) });
    await mount(makeRecord(SIGN_IN));
    expect(".o_social_sign_in").toHaveText("Sign in with LinkedIn");
    expect(".o_social_connect").toHaveCount(0);
    await contains(".o_social_sign_in").click();
    expect.verifySteps(["action_oauth_start", "open https://platform.example/authorize"]);
});

test("sign-in waits for the public address and a required Page ID", async () => {
    mockService("orm", { call: async () => expect.step("rpc") });
    const record = makeRecord({ ...SIGN_IN, public_url: false });
    await mount(record);
    expect(".o_social_sign_in").toHaveAttribute("disabled");
    expect(".alert-warning").toHaveCount(1);
    record.data.credentials_ui = { ...SIGN_IN, account_label: "LinkedIn Page ID", account_required: true };
    await animationFrame();
    expect(".o_social_sign_in").toHaveAttribute("disabled");
    await contains(".o_social_account").edit("123");
    expect(".o_social_sign_in").not.toHaveAttribute("disabled");
    expect.verifySteps([]);
});

test("a failed save sends nothing", async () => {
    mockService("orm", { call: async () => expect.step("rpc") });
    const record = makeRecord({ installed: true, label: "Demo", oauth: false });
    record.saved = false;
    await mount(record);
    await contains("input[type=password]").edit("secret-token");
    await contains(".o_social_connect").click();
    expect.verifySteps([]);
});

test("token entry stays available next to sign-in", async () => {
    mockService("orm", { call: async () => {} });
    await mount(makeRecord(SIGN_IN));
    await contains(".o_social_manual").click();
    expect(".o_social_connect").toHaveCount(1);
});
