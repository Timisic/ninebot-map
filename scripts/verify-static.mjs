import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {spawn, execFileSync} from 'node:child_process';
import {createServer} from 'node:http';
import path from 'node:path';
import {chromium} from 'playwright';
const root=process.cwd();
const output=process.env.VERIFICATION_OUTPUT || 'work/static-verification';
await fs.mkdir(output,{recursive:true});
const scratch=await fs.mkdtemp(path.join(root,'work/static-'));
const site=path.join(scratch,'map');
execFileSync('./run',['export-site','--dataset','tests/fixtures/synthetic-map.json','--output',site]);
const original=JSON.parse(await fs.readFile(path.join(site,'dataset.json'),'utf8'));
const types={'.html':'text/html','.mjs':'text/javascript','.js':'text/javascript','.css':'text/css','.json':'application/json','.png':'image/png'};
const requests=[];
const server=createServer(async(req,res)=>{
 requests.push({method:req.method,path:req.url});
 if(!['GET','HEAD'].includes(req.method)){res.writeHead(405);res.end();return;}
 const name=req.url==='/map/'?'index.html':req.url?.startsWith('/map/')?req.url.slice(5):null;
 if(!name||name.includes('..')||name.includes('?')){res.writeHead(404);res.end();return;}
 try{const bytes=await fs.readFile(path.join(site,name));res.writeHead(200,{'Content-Type':types[path.extname(name)]||'text/plain','Cache-Control':'no-store'});res.end(req.method==='HEAD'?undefined:bytes);}catch{res.writeHead(404);res.end();}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const origin=`http://127.0.0.1:${server.address().port}`;
let browser;
try{
 browser=await chromium.launch({...process.env.PLAYWRIGHT_CHANNEL==='chromium'?{}:{channel:process.env.PLAYWRIGHT_CHANNEL||'chrome'},headless:true});
 const page=await browser.newPage({viewport:{width:1280,height:800}});
 const errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',route=>{if(!route.request().url().startsWith(origin)){external.push(route.request().url());route.abort();}else route.continue();});
 await page.goto(origin+'/map/');
 await page.waitForFunction(()=>document.querySelector('#visible-stat').textContent.includes('12 次'));
 assert.equal(await page.locator('input[type=file],#import-button,#empty-import').count(),0);
 assert.equal(await page.title(),'Along');
 assert.equal(await page.locator('#date-panel,#from,#to').count(),0);
 await page.waitForFunction(()=>document.querySelector('#update-map').disabled&&document.querySelector('#update-map').title.includes('暂不支持'));
 assert.equal(await page.locator('#error').isVisible(),false);
 assert.match(await page.locator('#updated-at').textContent(),/2026/);
 await page.locator('#toggle-places').click();await page.locator('.place-button').first().click();
 await page.locator('#edit-place').click();await page.locator('#place-label').fill('静态地图名称');await page.locator('#label-form button[type=submit]').click();
 await page.screenshot({path:path.join(output,'static-before.png')});
 const updated=structuredClone(original);updated.updated_at='2026-10-05T08:00:00Z';
 await fs.writeFile(path.join(site,'dataset.next'),JSON.stringify(updated));await fs.rename(path.join(site,'dataset.next'),path.join(site,'dataset.json'));
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await page.waitForFunction(()=>document.querySelector('#updated-at').textContent.includes('10/5'));
 assert.equal(await page.locator('.place-name').first().textContent(),'静态地图名称');
 await fs.writeFile(path.join(site,'dataset.json'),'{}');
 await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await page.waitForFunction(()=>!document.querySelector('#error').hidden);
 assert.match(await page.locator('#visible-stat').textContent(),/12 次/);
 await fs.writeFile(path.join(site,'dataset.json'),JSON.stringify(updated));
 await page.goto(origin+'/map/index.html');await page.waitForFunction(()=>document.querySelector('#visible-stat').textContent.includes('12 次'));
 assert.equal(await page.locator('.place-name').first().textContent(),'静态地图名称');
 for(const route of ['/map/upload','/map/import','/map/.private/tokens.json','/map/data/','/map/nbmap/'])assert.equal((await fetch(origin+route)).status,404);
 assert.equal((await fetch(origin+'/map/dataset.json',{method:'POST',body:'{}'})).status,405);
 assert.deepEqual(external,[]);assert.deepEqual(errors,[]);
 await page.screenshot({path:path.join(output,'static-after.png')});
 await fs.writeFile(path.join(output,'static.json'),JSON.stringify({passed:true,synthetic:true,nestedPath:true,withoutETagRefresh:true,invalidReplacementRetainsVisibleMap:true,manualImportAbsent:true,external,errors,requests},null,2));
 console.log('Static map passed: nested paths, no import, no secrets, no-ETag refresh, saved labels, invalid update retention.');
}finally{await browser?.close();await new Promise(resolve=>server.close(resolve));await fs.rm(scratch,{recursive:true,force:true});}
