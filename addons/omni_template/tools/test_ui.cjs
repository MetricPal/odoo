// Mount the actual Owl 3 format widget, including reactive selection and readonly mode.
const fs=require('node:fs'),path=require('node:path');
const {createRequire}=require('node:module');
const {chromium}=createRequire(process.env.OMNI_NODE_MODULES+'/__template.cjs')('playwright');
const root=path.resolve(__dirname,'../../..');
const strip=s=>s.replace(/^import .*;\n/gm,'').replace(/\bexport /g,'');
(async()=>{const browser=await chromium.launch({headless:true});try{
 const page=await browser.newPage();page.on('pageerror',error=>{throw error;});await page.setContent('<div id="mount"></div>');
 await page.addScriptTag({path:path.join(root,'addons/web/static/lib/owl/owl.js')});
 await page.addScriptTag({content:'const {Component,useProps,proxy,t}=owl;const registry={category:()=>({add(){}})};class TextField extends Component{};const textField={};class ReferenceField extends Component{};const referenceField={};'});
 await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/web/static/src/views/fields/standard_field_props.js'),'utf8'))});
 await page.addScriptTag({content:strip(fs.readFileSync(path.join(root,'addons/omni_template/static/src/editor.js'),'utf8'))});
 await page.evaluate(async xml=>{
  const changes=[];const record={data:proxy({content_type:'message',format_choices:[['message','Message'],['photo','Photo']]}),update:async values=>{changes.push(values);Object.assign(record.data,values);}};
  const app=new owl.App({templates:xml,dev:true});
  const mounted=app.createRoot(TemplateFormat,{props:{id:'format',name:'content_type',record,readonly:false}});await mounted.mount(document.getElementById('mount'));
  const select=document.querySelector('select');if(select.options.length!==2||select.value!=='message')throw Error('Wrong formats');
  select.value='photo';select.dispatchEvent(new Event('change'));
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  if(record.data.content_type!=='photo'||changes.length!==1)throw Error('Selection update');
  record.data.format_choices=[['post','Post'],['carousel','Carousel']];record.data.content_type='post';
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
  if(select.options[0].text!=='Post'||select.value!=='post')throw Error('Reactive channel switch');
  mounted.destroy();
  await app.createRoot(TemplateFormat,{props:{id:'readonly',name:'content_type',record,readonly:true}}).mount(document.getElementById('mount'));
  if(document.querySelector('select')||document.getElementById('mount').textContent.trim()!=='Post')throw Error('Readonly mode');
 },fs.readFileSync(path.join(root,'addons/omni_template/static/src/editor.xml'),'utf8'));
 console.log('PASS: actual Owl 3 template/widget, reactive channel formats, editable and readonly selection');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
