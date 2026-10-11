const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { chromium } = createRequire(process.env.OMNI_NODE_MODULES + '/__wa_checks.cjs')('playwright');
const root = path.resolve(__dirname, '../../..');
const strip = text => text.replace(/^import .*;\n/gm, '').replace(/\bexport /g, '');
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    await page.exposeFunction('whatsappScreenshot', async () => {
      await page.locator('#mount').screenshot({path:'/tmp/whatsapp-credentials-actual.png'});
      for (const width of [780, 360]) {
        await page.setViewportSize({width,height:800});
        if(await page.locator('#mount').evaluate(el=>el.scrollWidth>el.clientWidth)) throw Error('Actual UI overflows at '+width);
      }
    });
    await page.setContent('<div id="mount"></div>');
    if (fs.existsSync('/tmp/web.assets_web.css')) {
      await page.addStyleTag({ path:'/tmp/web.assets_web.css' });
      await page.addStyleTag({content:'#mount { max-width:600px; padding:24px; margin:24px; }'});
    }
    await page.addScriptTag({ path: path.join(root, 'addons/web/static/lib/owl/owl.js') });
    await page.addScriptTag({content:'window.odoo = { debug: "assets" };'});
    await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/web/static/src/core/template_inheritance.js'),'utf8'))});
    await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/web/static/src/core/templates.js'),'utf8').replace(/^import[\s\S]*?from "@web\/core\/template_inheritance";\n/,''))});
    const templateFiles = ['addons/web/static/src/views/form/form_controller.xml','addons/omni_channel/static/src/channel_setup/channel_setup.xml','addons/omni_whatsapp/static/src/credentials/credentials.xml'];
    for(const relative of templateFiles){
      await page.evaluate(({xml,url})=>{
        const document=new DOMParser().parseFromString(xml,'text/xml');
        for(const template of document.querySelectorAll('[t-name]')) registerTemplate(template.getAttribute('t-name'),url,template.outerHTML);
      },{xml:fs.readFileSync(path.join(root,relative),'utf8'),url:'/'+relative.replace(/^addons\//,'')});
    }
    await page.evaluate(()=>{
      const merged=getTemplate('omni_whatsapp.ChannelSetup');
      new owl.App({templates:`<templates>${merged.outerHTML}</templates>`}).getTemplate('omni_whatsapp.ChannelSetup');
      if(!merged.querySelector('[t-if="this.setupState.step === 1 && !this.model.root.data.is_whatsapp"]')) throw Error('Inherited guidance does not preserve other providers');
    });
    await page.addScriptTag({ content: `const { Component, proxy, useProps, onWillUnmount, t } = owl;
      const registry = { category: () => ({ add() {} }) }; const formView = {};
      class ChannelSetupController { async goToStep(index) { this.nativeCalls.push(index); } }
      const useService = name => window.whatsappTestServices[name];` });
    await page.addScriptTag({ content: strip(fs.readFileSync(path.join(root, 'addons/web/static/src/views/fields/standard_field_props.js'), 'utf8')) });
    await page.addScriptTag({ content: strip(fs.readFileSync(path.join(root, 'addons/omni_whatsapp/static/src/credentials/credentials.js'), 'utf8')) });
    const xml = fs.readFileSync(path.join(root, 'addons/omni_whatsapp/static/src/credentials/credentials.xml'), 'utf8');
    const result = await page.evaluate(async xml => {
      const parsed = new DOMParser().parseFromString(xml, 'text/xml');
      const template = parsed.querySelector('[t-name="omni_whatsapp.Credentials"]').outerHTML;
      const record = { resId: 12, data: { whatsapp_credentials_ui: {} } };
      const calls = [];
      let resolveVerification;
      const orm = { call: async (...args) => { calls.push(args); return [{ id:'123',name:'Sales',number:'+60 12 345 6789' }, { id:'456',name:'Support',number:'+60 12 345 6790' }]; } };
      window.whatsappTestServices={orm};
      const app = new owl.App({ templates:`<templates>${template}</templates>`,env:{services:{orm}},dev:true });
      const mounted = app.createRoot(WhatsAppCredentials, {
        props:{id:'wa',name:'whatsapp_credentials_ui',record,readonly:false},env:{services:{orm}},dev:true });
      const component = await mounted.mount(document.getElementById('mount'));
      const tick = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const input = (id,value) => { const el=document.getElementById(id);el.value=value;el.dispatchEvent(new Event('input',{bubbles:true})); };
      if(document.querySelector('select')) throw Error('Phone picker shown before verification');
      input('wa_token','synthetic-token'); input('wa_account','987');
      await component.verify(); await tick();
      if(!document.querySelector('select') || component.state.selected) throw Error('Multiple numbers not explicit');
      document.querySelector('select').value='123';document.querySelector('select').dispatchEvent(new Event('change',{bubbles:true}));
      await tick(); if(component.state.selected!=='123') throw Error('Number selection failed');
      const controller = new WhatsAppSetupController(); controller.nativeCalls=[];controller.setupState={step:1,busy:false};
      record.data.is_whatsapp=true; controller.model={root:record,load:async()=>{record.data.setup_account_id=[7,'Saved'];}};
      controller.orm=orm;controller.notification={add(){throw Error('Unexpected warning');}};
      await controller.goToStep(2);
      if(component.state.token || controller.nativeCalls.join()!=='2' || calls[1][1]!=='action_whatsapp_save_connection') throw Error('Next did not save securely before native navigation');
      record.data.setup_account_id=false;
      input('wa_token','second-token');input('wa_account','988');
      if(component.state.numbers.length || component.state.selected) throw Error('Input edits retained old verification');
      orm.call = () => new Promise(resolve=>{resolveVerification=resolve;});
      const pending = component.verify();
      input('wa_account','989');resolveVerification([{id:'999',name:'Old',number:'old'}]);
      await pending;await tick();if(component.state.numbers.length) throw Error('Stale response certified changed input');
      orm.call=async()=>[{id:'777',name:'Only number',number:'+60 12 345 6789'}];
      await component.verify();await tick();
      if(document.querySelector('select').value!=='777') throw Error('Single number not visibly selected');
      await window.whatsappScreenshot?.();
      const other = new WhatsAppSetupController();other.nativeCalls=[];other.model={root:{data:{is_whatsapp:false}}};
      other.setupState={step:1,busy:false};await other.goToStep(2);
      if(other.nativeCalls.join()!=='2') throw Error('Non-WhatsApp navigation changed');
      app.destroy();if(component.state.token || drafts.has(record)) throw Error('Unmount retained credentials');
      return 'Actual Owl 3 component passed: fields, verification, explicit selection, invalidation, secure Next, stale response, non-WhatsApp delegation and unmount cleanup';
    }, xml);
    console.log(result);
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
