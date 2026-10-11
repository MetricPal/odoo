// Uses only a disposable test database and synthetic operator supplied by check_install.py.
const fs=require('node:fs');const {createRequire}=require('node:module');
const {chromium}=createRequire(process.env.OMNI_NODE_MODULES+'/__template_live.cjs')('playwright');
(async()=>{const fixture=JSON.parse(fs.readFileSync(process.env.OMNI_TEMPLATE_FIXTURE,'utf8'));const browser=await chromium.launch({headless:true});try{
 const base='http://localhost:8089';const context=await browser.newContext({viewport:{width:1400,height:1000}});
 let ready=false;for(let i=0;i<60;i++){try{await context.request.get(base+'/web/login');ready=true;break;}catch{await new Promise(r=>setTimeout(r,500));}}if(!ready)throw Error('Disposable server failed to start');
 const auth=await context.request.post(base+'/web/session/authenticate',{data:{jsonrpc:'2.0',method:'call',params:{db:fixture.database,login:fixture.login,password:fixture.password}}});const result=await auth.json();if(result.error||!result.result.uid)throw Error('Synthetic operator authentication failed');
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(base+'/odoo/action-'+fixture.action+'/'+fixture.template+'?debug=assets');
 await page.locator('.o_omni_template').waitFor({timeout:60000}).catch(async error=>{await page.screenshot({path:'/tmp/template-ui-error.png',fullPage:true});console.error('UI errors:',errors);console.error(await page.locator('body').innerText());throw error;});
 await page.locator('.omni_template_message').waitFor();
 if(!(await page.locator('.omni_template_message').innerText()).includes('Aisha Rahman'))throw Error('Record variables not resolved');
 await page.screenshot({path:'/tmp/omnichannel-templates-live.png',fullPage:true});
 const input=page.locator('.ot_editor textarea');await input.fill('Hello {{ object.name }} from {{ company.name }}');await input.blur();
 await page.waitForFunction(()=>document.querySelector('.omni_template_message')?.textContent.includes('Hello Aisha Rahman'));
 await page.getByRole('button',{name:'Bold',exact:true}).click();await input.blur();
 await page.getByRole('button',{name:'Insert field',exact:true}).click();
 await page.locator('.o_popover').waitFor({timeout:5000});
 await page.keyboard.press('Escape');
 await page.getByRole('tab',{name:'Options',exact:true}).click();await page.locator('[name="purpose_id"]').waitFor();
 await page.getByRole('tab',{name:'Content',exact:true}).click();
 await page.getByRole('button',{name:'+ Button',exact:true}).click();
 await page.locator('[name="button_label"] input').waitFor();
 await page.locator('[name="button_label"] input').fill('Get started');
 await page.locator('[name="button_url"] input').fill('https://example.com');await page.locator('[name="button_url"] input').blur();
 await page.locator('.ot_button').waitFor();
 await page.getByRole('button',{name:'− Button',exact:true}).click();await page.locator('.ot_button').waitFor({state:'hidden'});
 const channel=page.locator('[name="channel_type_id"] input');await channel.fill('WhatsApp');
 await page.getByRole('option',{name:'WhatsApp Business',exact:true}).click();
 const format=page.locator('[name="content_type"] select');await format.selectOption('wa_template');
 await page.getByText('Meta: Not submitted · Local draft only',{exact:true}).waitFor();
 await page.getByRole('button',{name:'+ Header',exact:true}).click();await page.locator('[name="header"] input').waitFor();
 await page.locator('[name="header"] input').fill('Welcome');await page.locator('[name="header"] input').blur();
 await page.locator('.ot_header').waitFor();
 await page.locator('.o_form_button_save').click();
 await page.waitForTimeout(300);
 const value=await context.request.post(base+'/web/dataset/call_kw/omni.template/read',{data:{jsonrpc:'2.0',method:'call',params:{model:'omni.template',method:'read',args:[[fixture.template],['content_type','header']],kwargs:{}}}});
 const saved=await value.json();if(saved.error||saved.result[0].content_type!=='wa_template'||saved.result[0].header!=='Welcome')throw Error('Native save failed');

 for(const width of [1024,360]){await page.setViewportSize({width,height:1000});await page.waitForTimeout(200);const overflow=await page.locator('.ot_workspace').evaluate(el=>el.scrollWidth>el.clientWidth+2);if(overflow)throw Error('Editor overflow at '+width);}
 if(errors.length)throw Error(errors.join('\n'));
 console.log('PASS: real Odoo form as operator, resolved preview/onchange, formatting, native field picker, tabs, desktop/mobile; no Owl errors');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
