const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const base = process.env.VIRAASAT_UI_TEST_URL || 'http://127.0.0.1:8766';
const target = new URL(base);
if (!['127.0.0.1', 'localhost'].includes(target.hostname) || process.env.VIRAASAT_UI_TEST_DISPOSABLE !== '1') {
  throw new Error('Use a disposable loopback test server and set VIRAASAT_UI_TEST_DISPOSABLE=1. This script creates fictional records.');
}
const output = process.env.VIRAASAT_UI_TEST_OUTPUT || '/private/tmp';
require('node:fs').mkdirSync(output, {recursive:true});
(async()=>{
const browser=await chromium.launch({headless:true, executablePath:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"});
try {
async function api(path,body,token){const r=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:JSON.stringify(body)});if(!r.ok)throw Error(path+': '+r.status+' '+await r.text());return r.json()}
const owner=await api('/users',{display_name:'Workspace Test Owner'});
const session=await api('/auth/login',{user_id:owner.id});
const token=session.access_token;
const viewer=await api('/users',{display_name:'Workspace Test Viewer'});
const circle=await api('/circles',{name:'Rao Test Family'},token);
await api(`/circles/${circle.id}/members`,{user_id:viewer.id,role:'viewer'},token);
const meera=await api(`/circles/${circle.id}/persons`,{full_name:'Meera Rao',birth_date:'1948-04-12',occupation:'Teacher',birth_place:'Mangaluru',bio_text:'An original family story.',medical_notes:'PRIVATE TEST NOTE'},token);
const kavya=await api(`/circles/${circle.id}/persons`,{full_name:'Kavya Rao',birth_date:'1975-06-21',occupation:'Architect',birth_place:'Bengaluru'},token);
await api(`/circles/${circle.id}/relationships`,{from_person_id:meera.id,to_person_id:kavya.id,relationship_type:'parent_of'},token);
const context=await browser.newContext({viewport:{width:1440,height:1000}});
await context.addInitScript(({token,id})=>{localStorage.setItem('authToken',token);localStorage.setItem('activeUserId',id)}, {token,id:owner.id});
const page=await context.newPage();page.setDefaultTimeout(10000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
await page.goto(base);await page.getByRole('heading',{name:'Family tree',exact:true}).waitFor();
await page.locator('.graph-node').first().waitFor();

await page.screenshot({path:output+'/viraasat-workspace-home.png',fullPage:true});
await page.locator('.ws-navigation').getByRole('button',{name:'People',exact:true}).click();
await page.locator('.ws-directory').getByRole('button',{name:/Meera Rao/}).click();
await page.getByRole('heading',{name:'Meera Rao',exact:true}).waitFor();
await page.getByRole('button',{name:'Edit profile',exact:true}).click();
await page.getByLabel('Biography and oral history notes',{exact:true}).fill('Draft survives navigation');
// A cancelled person change must keep the draft intact.
page.once('dialog', dialog => dialog.dismiss());
await page.locator('.ws-directory').getByRole('button',{name:/Kavya Rao/}).click();
assert.equal(await page.getByLabel('Biography and oral history notes',{exact:true}).inputValue(),'Draft survives navigation');
await page.locator('.ws-navigation').getByRole('button',{name:'Family tree',exact:true}).click();
await page.goBack();
assert.equal(await page.getByLabel('Biography and oral history notes',{exact:true}).inputValue(),'Draft survives navigation');
// Failed writes report failure locally and retain the same draft.
await page.route('**/persons/'+meera.id, async route => {
  if(route.request().method()==='PATCH') await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Temporary test failure'})});
  else await route.continue();
});
await page.getByRole('button',{name:'Save Profile',exact:true}).click();
await page.locator('.ws-save-feedback').filter({hasText:'Temporary test failure'}).waitFor();
assert.equal(await page.getByLabel('Biography and oral history notes',{exact:true}).inputValue(),'Draft survives navigation');
await page.unroute('**/persons/'+meera.id);
await page.getByRole('button',{name:'Save Profile',exact:true}).click();
await page.getByText('Changes saved.',{exact:true}).waitFor();
await page.getByRole('button',{name:'Close editor',exact:true}).click();
await page.locator('.ws-biography').filter({hasText:'Draft survives navigation'}).waitFor();
await page.getByRole('tab',{name:'Photos',exact:true}).click();
await page.getByText('No media for this person',{exact:true}).waitFor();
await page.getByRole('tab',{name:'Story',exact:true}).click();
await page.screenshot({path:output+'/viraasat-workspace-people.png',fullPage:true});
await page.locator('.ws-navigation').getByRole('button',{name:'Family tree',exact:true}).click();

await page.locator('.graph-node').first().waitFor();
await page.getByRole('button',{name:'Fit tree',exact:true}).click();
await page.waitForTimeout(400);
assert.equal(await page.evaluate(()=>{const viewport=document.querySelector('.graph-scroll').getBoundingClientRect();const node=document.querySelector('.graph-node').getBoundingClientRect();return node.right>viewport.left && node.left<viewport.right && node.bottom>viewport.top && node.top<viewport.bottom;}),true,'graph node outside viewport after Fit');
assert.equal(await page.evaluate(()=>{const v=document.querySelector('.graph-scroll').getBoundingClientRect();const n=document.querySelector('.graph-node').getBoundingClientRect();return Math.abs((n.left+n.right)/2-(v.left+v.right)/2)<40 && n.width>200;}),true,'small tree must be centered and readable after Fit');
await page.evaluate(()=>window.scrollTo(0,0));
assert.equal(await page.evaluate(()=>{const v=document.querySelector('.graph-scroll').getBoundingClientRect();return [...document.querySelectorAll('.graph-node')].every(node=>{const n=node.getBoundingClientRect();return n.top>=v.top && n.bottom<=v.bottom && n.left>=v.left && n.right<=v.right;});}),true,'Fit must show every card without clipping');
await page.screenshot({path:output+'/viraasat-workspace-tree.png',fullPage:true});
await page.locator('.ws-graph-options>summary').click();
assert.equal(await page.evaluate(()=>{const c=document.querySelector('.ws-tree-controls').getBoundingClientRect();const g=document.querySelector('.graph-scroll').getBoundingClientRect();return c.bottom<=g.top+1;}),true,'tree controls overlap the graph viewport');
await page.evaluate(()=>window.scrollTo(0,0));
await page.screenshot({path:output+'/viraasat-tree-expanded.png',fullPage:true});
await page.locator('.ws-graph-options>summary').click();

await page.locator('.ws-navigation').getByRole('button',{name:'Places & time',exact:true}).click();
await page.getByText('No places for this person',{exact:true}).waitFor();
await page.screenshot({path:output+'/viraasat-workspace-places.png',fullPage:true});
await page.getByText('Add a place',{exact:true}).click();
await page.getByRole('button',{name:'Add Place',exact:true}).waitFor();
await page.locator('.ws-place-person select').focus();
assert.equal(await page.evaluate(()=>{const l=document.querySelector('.ws-place-person>span').getBoundingClientRect();const s=document.querySelector('.ws-place-person select').getBoundingClientRect();return s.top-l.bottom>=8;}),true,'selector focus overlaps its label');
await page.screenshot({path:output+'/viraasat-places-expanded.png',fullPage:true});
await page.setViewportSize({width:390,height:844});
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'expanded places overflow on mobile');
await page.evaluate(()=>window.scrollTo(0,0));
await page.screenshot({path:output+'/viraasat-places-expanded-mobile.png',fullPage:false});
await page.setViewportSize({width:1440,height:1000});

await page.getByRole('button',{name:'Family access',exact:true}).click();
await page.screenshot({path:output+'/viraasat-workspace-access.png',fullPage:true});
await page.getByRole('button',{name:'Invite someone',exact:true}).click();
await page.getByRole('button',{name:'Send Invite',exact:true}).waitFor();
// The full existing journey must still save and reveal a new node.
await page.locator('.ws-navigation').getByRole('button',{name:'People',exact:true}).click();
assert.equal(await page.getByRole('button',{name:'＋ Add person',exact:true}).count(),1);
await page.getByRole('button',{name:'＋ Add person',exact:true}).click();
await page.getByLabel('Their name *',{exact:true}).fill('Tara Workspace Test');
await page.getByRole('dialog').getByRole('button',{name:'Skip optional details',exact:true}).click();
await page.getByRole('dialog').getByRole('button',{name:'Add to our family',exact:true}).click();
await page.getByRole('button',{name:'See their place in the tree',exact:true}).click();
await page.waitForURL('**/#tree');
await page.locator('.graph-node[aria-label*="Tara Workspace Test"]').waitFor();
await page.setViewportSize({width:390,height:844});
await page.locator('.ws-mobile-nav').getByRole('button',{name:'People',exact:true}).click();
await page.screenshot({path:output+'/viraasat-workspace-mobile.png',fullPage:true});
assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'mobile page overflow');
await page.locator('.ws-account-menu>summary').click();
await page.getByRole('button',{name:'Sign out',exact:true}).click();
await page.getByRole('heading',{name:'Continue your family archive',exact:true}).waitFor();
assert.equal(await page.locator('.ws-person-sheet').count(),0,'private profile remains after logout');
assert.equal(await page.getByText('Draft survives navigation',{exact:true}).count(),0);
// Use a separate authenticated viewer, not an owner UI with buttons hidden by a mock.
const viewerLogin=await api('/auth/login',{user_id:viewer.id});
const viewerContext=await browser.newContext({viewport:{width:1440,height:1000}});
await viewerContext.addInitScript(({token,id})=>{localStorage.setItem('authToken',token);localStorage.setItem('activeUserId',id)}, {token:viewerLogin.access_token,id:viewer.id});
const viewerPage=await viewerContext.newPage();viewerPage.setDefaultTimeout(10000);
viewerPage.on('pageerror', e=>errors.push(e.message));
await viewerPage.goto(base+'/#people');
await viewerPage.locator('.ws-directory').getByRole('button',{name:/Meera Rao/}).click();
await viewerPage.getByText('Medical notes are visible only to owners and editors.',{exact:true}).first().waitFor();
assert.equal(await viewerPage.getByRole('button',{name:'Edit profile',exact:true}).count(),0);
assert.equal(await viewerPage.getByRole('button',{name:'＋ Add person',exact:true}).count(),0);
assert.equal(await viewerPage.locator('body').textContent().then(text=>text.includes('PRIVATE TEST NOTE')),false);
await viewerPage.getByRole('tab',{name:'Photos',exact:true}).click();
await viewerPage.getByText('No media for this person',{exact:true}).waitFor();
await viewerContext.close();
assert.deepEqual(errors,[]);
console.log('PASS: real local API, navigation/back, profile save/draft retention, lazy media, graph, places, invitations, add-person save/reveal, mobile overflow, logout, real viewer permissions and medical privacy.');
} finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
