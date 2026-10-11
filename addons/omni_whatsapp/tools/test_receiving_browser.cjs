const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { chromium } = createRequire(process.env.OMNI_NODE_MODULES + '/__wa_checks.cjs')('playwright');
const root = path.resolve(__dirname, '../../..');
const strip = text => text.replace(/^import .*;\n/gm, '').replace(/\bexport /g, '');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:780,height:900}});
    await page.setContent('<div id="mount"></div>');
    if(fs.existsSync('/tmp/web.assets_web.css')) await page.addStyleTag({path:'/tmp/web.assets_web.css'});
    await page.addStyleTag({content:'#mount{max-width:680px;padding:24px;margin:12px}'});
    await page.addScriptTag({path:path.join(root,'addons/web/static/lib/owl/owl.js')});
    await page.addScriptTag({content:'const {Component,proxy,useProps,onWillUnmount,t}=owl; const registry={category:()=>({add(){}})}; const useService=()=>window.waOrm;'});
    await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/web/static/src/views/fields/standard_field_props.js'),'utf8'))});
    await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/omni_whatsapp/static/src/credentials/receiving.js'),'utf8'))});
    const xml=fs.readFileSync(path.join(root,'addons/omni_whatsapp/static/src/credentials/credentials.xml'),'utf8');
    await page.evaluate(async xml=>{
      const template=new DOMParser().parseFromString(xml,'text/xml').querySelector('[t-name="omni_whatsapp.Receiving"]').outerHTML;
      const calls=[];
      const record={resId:12,data:{whatsapp_receiving_ui:{url:'https://channels.example.com/omni/inbound/4e612745-603e-41b8-9d21-b5347a18c742',token:'generated-test-token',saved:false,verified:false,enabled:false}},
        save:async()=>{calls.push('native-save');return true;},model:{load:async()=>calls.push('reload')}};
      window.waOrm={call:async(model,method,args)=>calls.push({method,args})};
      const app=new owl.App({templates:`<templates>${template}</templates>`,dev:true});
      window.waRoot=app.createRoot(WhatsAppReceiving,{props:{id:'wa',name:'whatsapp_receiving_ui',record,readonly:false}});
      const component=await window.waRoot.mount(document.getElementById('mount'));
      const tick=()=>new Promise(r=>setTimeout(r,25));
      if(document.querySelector('input[readonly]').value!=='generated-test-token')throw Error('Missing generated token');
      component.state.secret='a'.repeat(32); await component.act(); await tick();
      if(calls[0]!=='native-save' || calls[1].method!=='action_whatsapp_save_webhook')throw Error('Webhook save bypassed native retention save');
      if(component.state.secret || document.querySelector('input[type=password]').value)throw Error('Saved secret retained');
      if(JSON.stringify(calls[1].args)!==JSON.stringify([[12],component.state.url,'a'.repeat(32)]))throw Error('Webhook save payload changed');
      record.data.whatsapp_receiving_ui={...record.data.whatsapp_receiving_ui,saved:true};
      await component.act();
      if(calls.at(-2).method!=='action_setup_enable_receiving')throw Error('Enable action not delegated to core authorization');
      record.data.whatsapp_receiving_ui={...record.data.whatsapp_receiving_ui,verified:true,enabled:true};
      component.state.url='https://updated.example.com/omni/inbound/route'; await tick(); await component.act();
      if(calls.at(-2).method!=='action_whatsapp_save_webhook')throw Error('Changed callback did not save before activation');
      record.save=async()=>false;const count=calls.length;await component.act();if(calls.length!==count)throw Error('RPC ran after native save refusal');
      record.save=async()=>true;window.waOrm.call=async()=>{throw Error('Synthetic provider rejection')};
      try{await component.act();throw Error('RPC rejection swallowed');}catch(e){if(e.message!=='Synthetic provider rejection')throw e;}
      if(component.state.busy)throw Error('Failed RPC left controls busy');
      record.data.whatsapp_receiving_ui={...record.data.whatsapp_receiving_ui,saved:false,enabled:false,verified:false};
      component.state.url=record.data.whatsapp_receiving_ui.url;await tick();
      window.waComponent=component;window.waApp=app;
    },xml);
    await page.locator('#mount').screenshot({path:'/tmp/whatsapp-webhook-actual.png'});
    for(const width of [780,360]){
      await page.setViewportSize({width,height:900});
      if(await page.locator('#mount').evaluate(el=>el.scrollWidth>el.clientWidth))throw Error('Receiving screen overflows at '+width);
    }
    await page.evaluate(()=>{waComponent.state.secret='temporary';waApp.destroy();if(waComponent.state.secret)throw Error('Unmount retained app secret');});
    console.log('Actual Owl receiving component passed: URL/token fields, native retention save, secret clearing, core activation, changed URL, failed save/RPC, mobile overflow and unmount.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
