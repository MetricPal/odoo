// Compile the actual combined card with the checked-out Odoo 20 compiler and Owl.
const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const runtimeRequire = process.env.OMNI_NODE_MODULES
    ? createRequire(path.join(process.env.OMNI_NODE_MODULES, '__omni_checks.cjs')) : require;
const { chromium } = runtimeRequire('playwright');
const repo = path.resolve(__dirname, '../../..');
const strip = s => s.replace(/^import[\s\S]*?from\s+["'][^"']+["'];\s*/gm, '').replace(/\bexport /g, '');
(async () => {
    const browser = await chromium.launch({ headless: true });
    try {
        const page = await browser.newPage();
        await page.setContent('<div id="test-root"></div>');
        await page.addScriptTag({ path: path.join(repo, 'addons/web/static/lib/owl/owl.js') });
        await page.addScriptTag({ content: 'const isIterable = x => x != null && typeof x[Symbol.iterator] === "function";' + strip(fs.readFileSync(path.join(repo, 'addons/web/static/src/core/utils/xml.js'), 'utf8')) });
        const utils = fs.readFileSync(path.join(repo, 'addons/web/static/src/views/utils.js'), 'utf8');
        await page.addScriptTag({ content: utils.match(/export const BUTTON_CLICK_PARAMS = \[[\s\S]*?\];/)[0].replace('export ', '') + '\n' + utils.match(/export function toStringExpression\(str\) \{[\s\S]*?\n\}/)[0].replace('export ', '') + '\nconst xml = owl.xml;' });
        for (const relative of ['addons/web/static/src/views/view_compiler.js', 'addons/web/static/src/views/card/card_compiler.js']) {
            await page.addScriptTag({ content: strip(fs.readFileSync(path.join(repo, relative), 'utf8')) });
        }
        const arch = fs.readFileSync(process.argv[2], 'utf8');
        const result = await page.evaluate(arch => {
            const root = parseXML(arch);
            const card = root.querySelector('t[t-name="card"]');
            let index = 0;
            for (const field of card.querySelectorAll('field')) field.setAttribute('field_id', `${field.getAttribute('name')}_${index++}`);
            class Root extends owl.Component { static template = owl.xml`<div/>`; }
            function compile(node) {
                const template = new CardCompiler({ card: node }).compile('card');
                const app = new owl.App(Root);
                app.addTemplate('card-check', template);
                app.getTemplate('card-check');
            }
            compile(card);
            const regression = card.cloneNode(true);
            const wrapper = regression.querySelector('t[t-else] > field[name="telegram_overview_status"]')?.parentElement;
            if (!wrapper) throw new Error('Missing status fallback wrapper');
            const field = wrapper.firstElementChild;
            field.setAttribute('t-else', '');
            wrapper.replaceWith(field);
            let rejected = false;
            try { compile(regression); } catch (error) { rejected = error.message.includes('Failed to compile'); }
            if (!rejected) throw new Error('Regression fixture did not reproduce the reported failure');
            return 'Odoo CardCompiler and Owl: corrected card compiles; original bug reproduced';
        }, arch);
        console.log(result);
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
