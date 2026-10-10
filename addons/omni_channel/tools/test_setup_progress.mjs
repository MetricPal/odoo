import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../static/src/setup_progress/setup_progress.js', import.meta.url), 'utf8');
const registrations = new Map();
const context = vm.createContext({ Component: class {}, useProps: () => ({}), standardFieldProps: {}, registry: { category: () => ({ add: (name, widget) => registrations.set(name, widget) }) } });
vm.runInContext(source.replace(/^import .*;\n/gm, '').replace('export class', 'class'), context);
const widget = registrations.get('omni_setup_progress');
assert.equal(widget.supportedTypes[0], 'integer');
const field = new widget.component();
field.props = { name: 'setup_completed_steps', record: { data: { setup_completed_steps: 0 } } };
assert.equal(field.completed, 0);
field.props.record.data.setup_completed_steps = 2;
assert.equal(field.completed, 2);
field.props.record.data.setup_completed_steps = 5;
assert.equal(field.completed, 5);
for (const value of [-1, 9, undefined]) {
    field.props.record.data.setup_completed_steps = value;
    assert.ok(field.completed >= 0 && field.completed <= 5);
}
console.log('Progress widget updates with the record and stays within five steps');
