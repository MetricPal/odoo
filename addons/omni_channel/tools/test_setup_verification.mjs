// Exercise the actual controller hook without starting an Odoo browser/database.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const source = readFileSync(new URL('../static/src/channel_setup/channel_setup.js', import.meta.url), 'utf8');
const hook = source.slice(source.indexOf('    async beforeExecuteActionButton('), source.indexOf('    async selectSetupStep('));
class NativeController {
    async beforeExecuteActionButton() {
        this.saves++;
        if (this.saveError) throw this.saveError;
        return this.saved;
    }
}
const Controller = new Function('NativeController', `return class extends NativeController { ${hook} }`)(NativeController);
for (const [token, saved, expected, notifications] of [
    ['new token', true, false, 1], ['', true, true, 0], ['new token', false, false, 0],
]) {
    const controller = new Controller();
    controller.model = { root: { data: { setup_bot_token: token } } };
    controller.saved = saved; controller.saves = 0;
    const actions = [];
    controller.actionService = { doAction: async action => actions.push(action) };
    assert.equal(await controller.beforeExecuteActionButton({ name: 'action_setup_verify_bot' }), expected);
    assert.equal(controller.saves, 1);
    assert.equal(actions.length, notifications);
    controller.saveError = new Error('Save failed');
    await assert.rejects(controller.beforeExecuteActionButton({ name: 'action_setup_verify_bot' }), /Save failed/);
    assert.equal(actions.length, notifications);
}
console.log('Passed: new credentials verify only on save; existing connections recheck; failed saves never show success.');

const overviewSource = source.slice(source.indexOf('class ChannelListController'), source.indexOf('export class ChannelSetupController'));
assert.ok(!overviewSource.includes('openRecord('), 'Record navigation must use native view controls, not controller overrides');

const selectHook = source.slice(source.indexOf('    async selectSetupStep('), source.indexOf('    async goToStep('));
const StepSelector = new Function(`return class { ${selectHook} }`)();
const selector = new StepSelector();
selector.setupState = { step: 2, completed: [0, 1] };
const visited = [];
selector.goToStep = async index => visited.push(index);
for (const index of [0, 1, 2, 3, 4, 5]) await selector.selectSetupStep(index);
assert.deepEqual(visited, [0, 1, 2]);
console.log('Passed: unfinished sidebar steps cannot be selected, including the next step.');

const parserSource = source.slice(source.indexOf('class ChannelListArchParser'), source.indexOf('class ChannelListController'));
const Parser = new Function('listView', `${parserSource}; return ChannelListArchParser;`)({ ArchParser: class {
    parse(...args) { return { nativeFields: true, args, noOpen: false }; }
} });
const parsed = new Parser().parse('arch', 'models', 'omni.channel');
assert.equal(parsed.noOpen, true);
assert.equal(parsed.nativeFields, true);
assert.deepEqual(parsed.args, ['arch', 'models', 'omni.channel']);
console.log('Passed: channel parser enables native noOpen while preserving parsed view data.');

const deferMethods = source.slice(source.indexOf('    async deferReceiving('), source.indexOf('    resizeSteps('));
const DraftController = new Function(`return class { ${deferMethods} }`)();
for (const succeeds of [true, false]) {
    const draft = new DraftController();
    draft.setupState = { step: 2, completed: [0, 1], busy: false };
    draft.save = async () => succeeds;
    const calls = [];
    draft.orm = { call: async (...args) => calls.push(args) };
    draft.model = { root: { resId: 42 }, load: async () => {} };
    await draft.deferReceiving();
    assert.equal(draft.setupState.step, succeeds ? 3 : 2);
    assert.deepEqual(draft.setupState.completed, [0, 1]);
    assert.equal(draft.setupState.busy, false);
    assert.equal(calls.length, succeeds ? 1 : 0);
    if (succeeds) assert.equal(calls[0][1], 'action_setup_defer_receiving');
    draft.actionService = { doAction: async (...args) => calls.push(args) };
    const before = calls.length;
    await draft.saveSetupDraft();
    assert.equal(calls.length, before + (succeeds ? 1 : 0));
    if (succeeds) assert.deepEqual(calls.at(-1), ['omni_channel.action_channels']);
}
console.log('Passed: deferring advances only after save, preserves incomplete receiving, and draft exit never completes setup.');
