// Mount the real progress field with the checked-out Owl 3 runtime.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const runtimeRequire = process.env.OMNI_NODE_MODULES
    ? createRequire(path.join(process.env.OMNI_NODE_MODULES, '__omni_checks.cjs')) : require;
const { chromium } = runtimeRequire('playwright');
const repo = path.resolve(__dirname, '../../..');
const strip = source => source.replace(/^import .*;\n/gm, '').replace(/\bexport /g, '');
(async () => {
    const browser = await chromium.launch({ headless: true });
    try {
        const page = await browser.newPage();
        await page.setContent('<main id="progress-test"></main>');
        await page.addScriptTag({ path: path.join(repo, 'addons/web/static/lib/owl/owl.js') });
        await page.addScriptTag({ content: 'const { Component, useProps, t } = owl; const registry = { category: () => ({ add() {} }) };' });
        for (const relative of ['addons/web/static/src/views/fields/standard_field_props.js', 'addons/omni_channel/static/src/setup_progress/setup_progress.js']) {
            await page.addScriptTag({ content: strip(fs.readFileSync(path.join(repo, relative), 'utf8')) });
        }
        const template = fs.readFileSync(path.join(repo, 'addons/omni_channel/static/src/setup_progress/setup_progress.xml'), 'utf8');
        const result = await page.evaluate(async templates => {
            const record = owl.proxy({ data: { setup_completed_steps: 0 } });
            await owl.mount(SetupProgress, document.getElementById('progress-test'), {
                props: { name: 'setup_completed_steps', record, readonly: true }, templates, dev: true,
            });
            const bar = document.querySelector('[role="progressbar"]');
            function check(value) {
                if (bar.getAttribute('aria-valuenow') !== String(value)) throw new Error('Wrong accessible progress value');
                if (bar.querySelectorAll('.o_omni_setup_track').length !== 1) throw new Error('Expected one continuous track');
                if (bar.querySelector('.o_omni_setup_fill').style.width !== `${value * 20}%`) throw new Error('Wrong continuous fill width');
                if (bar.textContent.trim() !== `${value}/5`) throw new Error('Wrong trailing counter');
            }
            check(0);
            for (const value of [2, 5]) {
                record.data.setup_completed_steps = value;
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                check(value);
            }
            return 'Mounted with Owl 3: 0/5, 2/5 and 5/5 render and update correctly';
        }, template);
        console.log(result);
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
