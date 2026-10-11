const fs=require('node:fs'),path=require('node:path');
const {createRequire}=require('node:module');
const {chromium}=createRequire(process.env.OMNI_NODE_MODULES+'/__social.cjs')('playwright');
const root=path.resolve(__dirname,'../../..');
const strip=s=>s.replace(/^import .*;\n/gm,'').replace(/\bexport /g,'');
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage();await page.setContent('<div id="mount" style="padding:24px;max-width:600px"></div>');
 if(fs.existsSync('/tmp/web.assets_web.css'))await page.addStyleTag({path:'/tmp/web.assets_web.css'});
 await page.addScriptTag({path:path.join(root,'addons/web/static/lib/owl/owl.js')});
 await page.addScriptTag({content:'const {Component,proxy,useProps,onWillUnmount,t}=owl;const registry={category:()=>({add(){}})};const useService=()=>window.fakeOrm;'});
 await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/web/static/src/views/fields/standard_field_props.js'),'utf8'))});
 await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/omni_social/static/src/credentials.js'),'utf8'))});
 await page.evaluate(async xml=>{
  let calls=0,saves=0,loads=0;
  window.fakeOrm={call:async(...args)=>{calls++;if(!['action_connect','action_configure_webhook'].includes(args[1]))throw Error('Wrong RPC');}};
  const record={resId:1,data:proxy({provider:'linkedin',account_kind:'organization'}),save:async()=>{saves++;return true;},model:{load:async()=>{loads++;}}};
  const app=new owl.App({templates:xml,dev:true});
  const component=await app.createRoot(SocialCredentials,{props:{id:'social',name:'credentials_ui',record,readonly:false}}).mount(document.getElementById('mount'));
  component.state.token='synthetic';component.state.account='123';
  await component.connect();if(calls!==1||saves!==1||loads!==1||component.state.token)throw Error('Secure save lifecycle failed');
  component.state.token='synthetic';record.save=async()=>false;await component.connect();if(calls!==1)throw Error('RPC after failed save');
  record.data.account_kind='person';await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));if(document.querySelectorAll('input').length!==1)throw Error('Personal profile inputs: '+document.querySelectorAll('input').length+'; '+document.getElementById('mount').innerHTML);
  record.save=async()=>true;record.data.connected=true;record.data.provider='instagram';component.state.secret='synthetic-app-secret';
  await component.webhook();if(calls!==2||component.state.secret)throw Error('Webhook secret lifecycle failed');
  record.data.account_kind='person';record.data.provider='linkedin';await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));if(document.querySelector('[id$="_secret"]'))throw Error('Personal LinkedIn webhook exposed');
  record.data.account_kind='organization';record.data.connected=false;
  window.socialComponent=component;window.socialRecord=record;
 },fs.readFileSync(path.join(root,'addons/omni_social/static/src/credentials.xml'),'utf8'));
 for(const width of [1200,360]){await page.setViewportSize({width,height:800});if(await page.locator('#mount').evaluate(el=>el.scrollWidth>el.clientWidth))throw Error('Overflow at '+width);}
 await page.screenshot({path:'/tmp/social-ui.png'});
 console.log('PASS: actual Owl 3 template/component, conditional Page ID, save/RPC/reload, secret clearing, failed-save guard, desktop/mobile');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
