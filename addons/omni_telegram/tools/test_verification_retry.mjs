import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../static/src/verification_retry.js', import.meta.url), 'utf8')
    .replace(/^import .*;\n/gm, '').replace('export function', 'function');
let options, calls = 0, closed = 0, result, resolve, actions = [], dialogs = [];
const services = {
    notification: { add: (_message, opts) => { options = opts; return () => closed++; } },
    orm: { call: async (...args) => { calls++; assert.deepEqual(JSON.parse(JSON.stringify(args)), ['omni.account', 'action_verify_telegram_bot', [[7]]]); return await result; } },
    action: { doAction: async value => actions.push(value) },
    dialog: { add: (_component, props) => dialogs.push(props) },
};
const context = vm.createContext({ registry: { category: () => ({ add() {} }) }, useService: name => services[name], _t: x => x, AlertDialog: {} });
vm.runInContext(source, context);
const params = { model: 'omni.account', method: 'action_verify_telegram_bot', record_id: 7, message: 'Try again', details: 'Safe details' };
context.verificationRetry({}, { params });
assert.equal(calls, 0, 'No automatic retry');
options.buttons[1].onClick(); assert.equal(dialogs[0].body, 'Safe details');
result = new Promise(r => resolve = r);
const pending = options.buttons[0].onClick();
await options.buttons[0].onClick(); assert.equal(calls, 1, 'Double click must not duplicate requests');
resolve({ tag: 'display_notification', params: { type: 'success' } }); await pending;
assert.equal(closed, 1); assert.equal(actions.at(-1), 'soft_reload');
context.verificationRetry({}, { params });
result = { tag: 'omni_telegram.verification_retry', params };
await options.buttons[0].onClick(); assert.equal(actions.at(-1).tag, 'omni_telegram.verification_retry');
context.verificationRetry({}, { params });
result = Promise.reject(new Error('RPC failed'));
await assert.rejects(options.buttons[0].onClick());
result = { tag: 'display_notification', params: { type: 'success' } };
await options.buttons[0].onClick(); assert.equal(actions.at(-1), 'soft_reload', 'Retry remains usable after RPC failure');
options = null;
context.verificationRetry({}, { params: { ...params, method: 'unlink' } }); assert.equal(options, null);
console.log('Passed: explicit retry, double-click guard, separate details, repeated failures, success refresh, restricted methods.');
