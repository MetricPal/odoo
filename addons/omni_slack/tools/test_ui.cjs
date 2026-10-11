const fs=require('node:fs'),path=require('node:path');
const {createRequire}=require('node:module');
const {chromium}=createRequire(process.env.OMNI_NODE_MODULES+'/__slack.cjs')('playwright');
const root=path.resolve(__dirname,'../../..');
const strip=s=>s.replace(/^import .*;\n/gm,'').replace(/\bexport /g,'');
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage();await page.setContent('<div id="mount" style="padding:24px;max-width:600px"></div>');
 if(fs.existsSync('/tmp/web.assets_web.css'))await page.addStyleTag({path:'/tmp/web.assets_web.css'});
 await page.addScriptTag({path:path.join(root,'addons/web/static/lib/owl/owl.js')});
 await page.addScriptTag({content:'window.odoo={debug:"assets"};'});
 await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/web/static/src/core/template_inheritance.js'),'utf8'))});
 await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/web/static/src/core/templates.js'),'utf8').replace(/^import[\s\S]*?from "@web\/core\/template_inheritance";\n/,''))});
 for(const relative of ['addons/web/static/src/views/form/form_controller.xml','addons/omni_channel/static/src/channel_setup/channel_setup.xml','addons/omni_whatsapp/static/src/credentials/credentials.xml','addons/omni_slack/static/src/setup.xml']){
  await page.evaluate(({xml,url})=>{const d=new DOMParser().parseFromString(xml,'text/xml');for(const t of d.querySelectorAll('[t-name]'))registerTemplate(t.getAttribute('t-name'),url,t.outerHTML);},{xml:fs.readFileSync(path.join(root,relative),'utf8'),url:relative});
 }
 await page.evaluate(()=>{for(const name of ['omni_channel.ChannelSetup','omni_whatsapp.ChannelSetup'])new owl.App({templates:`<templates>${getTemplate(name).outerHTML}</templates>`}).getTemplate(name);});
 await page.addScriptTag({content:'const {Component,proxy,useProps,onWillUnmount,t}=owl;const registry={category:()=>({add(){}})};const useService=()=>window.fakeOrm;'});
 await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/web/static/src/views/fields/standard_field_props.js'),'utf8'))});
 await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/omni_slack/static/src/setup.js'),'utf8'))});
 await page.evaluate(async xml=>{
  const d=new DOMParser().parseFromString(xml,'text/xml');let calls=0,saves=0,loads=0;
  window.fakeOrm={call:async(...args)=>{calls++;if(args[1]!=='action_slack_connect')throw Error('Wrong RPC');}};
  const record={resId:1,data:{slack_credentials_ui:{}},save:async()=>{saves++;return true;},model:{load:async()=>{loads++;}}};
  const app=new owl.App({templates:`<templates>${d.querySelector('[t-name="omni_slack.Credentials"]').outerHTML}</templates>`,dev:true});
  const component=await app.createRoot(SlackCredentials,{props:{id:'slack',name:'slack_credentials_ui',record,readonly:false}}).mount(document.getElementById('mount'));
  component.state.token='xoxb-synthetic';component.state.secret='synthetic';component.state.app='ATEST';
  await component.connect();if(calls!==1||saves!==1||loads!==1||component.state.token||component.state.secret)throw Error('Secure save lifecycle failed');
  record.save=async()=>false;await component.connect();if(calls!==1)throw Error('RPC after failed save');
 },fs.readFileSync(path.join(root,'addons/omni_slack/static/src/setup.xml'),'utf8'));
 for(const width of [1200,360]){await page.setViewportSize({width,height:800});if(await page.locator('#mount').evaluate(el=>el.scrollWidth>el.clientWidth))throw Error('Overflow at '+width);}
 await page.screenshot({path:'/tmp/slack-ui.png'});console.log('PASS: actual Owl 3 component/template, save/RPC/reload, secret clearing, failed-save guard, desktop/mobile');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
