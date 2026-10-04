import { chromium } from 'playwright';
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';
const root = new URL('../', import.meta.url);
const browser = await chromium.launch({...(process.env.PLAYWRIGHT_CHANNEL === 'chromium' ? {} : { channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome' }), headless: true});
try {
  const source = await fs.readFile(new URL('web/wheel-zoom.mjs',root),'utf8');
  const rawTraces = [];
  for (const deviceScaleFactor of [1,2]) {
    const rawPage = await browser.newPage({viewport:{width:800,height:600},deviceScaleFactor});
    await rawPage.setContent('<div id="map" style="width:800px;height:600px"></div>');
    await rawPage.addScriptTag({path:new URL('web/vendor/leaflet/leaflet.js',root).pathname});
    await rawPage.addScriptTag({content:source.replace('export function installWheelZoom(map)', 'window.installWheelZoom = function(map)')});
    const trace = await rawPage.evaluate(async () => {
      const map = L.map('map',{scrollWheelZoom:false,zoomAnimation:false,minZoom:3,maxZoom:19,zoomSnap:1}).setView([0,0],13);
      installWheelZoom(map);
      const events = [];
      const wait = () => new Promise(resolve => setTimeout(resolve,120));
      const send = (deltaY,ctrlKey=false) => {
        const event = new WheelEvent('wheel',{deltaY,ctrlKey,deltaMode:0,clientX:400,clientY:300,bubbles:true,cancelable:true});
        const before = map.getZoom(), normalized = L.DomEvent.getWheelDelta(event);
        map.getContainer().dispatchEvent(event);
        events.push({deltaY,ctrlKey,normalized,before,after:map.getZoom()});
      };
      const result = {};
      send(-1);await wait();result.tiny=map.getZoom();
      send(-300);result.normal300=map.getZoom();await wait();map.setZoom(13);
      for(let i=0;i<8;i++) send(-120);
      result.burst=map.getZoom();await wait();
      send(400);result.freshReverse400=map.getZoom();await wait();map.setZoom(13);
      send(-1,true);result.tinyPinch=map.getZoom();await wait();
      send(-100,true);result.pinch100=map.getZoom();
      const platform = navigator.platform, dpr = devicePixelRatio;
      map.remove();return {platform,dpr,events,result};
    });
    rawTraces.push(trace);
    await rawPage.close();
  }
  console.log(JSON.stringify({kind:'Raw pixel delta input through production handler and native Leaflet DPR normalization',rawTraces},null,2));
  for(const trace of rawTraces) assert.deepEqual(trace.result,{tiny:13,normal300:14,burst:14,freshReverse400:13,tinyPinch:13,pinch100:14});
  const page = await browser.newPage({viewport:{width:800,height:600}});
  await page.setContent('<div id="map" style="width:800px;height:600px"></div>');
  await page.addStyleTag({path:new URL('web/vendor/leaflet/leaflet.css',root).pathname});
  await page.addScriptTag({path:new URL('web/vendor/leaflet/leaflet.js',root).pathname});
  await page.addScriptTag({content:(await fs.readFile(new URL('web/wheel-zoom.mjs',root),'utf8')).replace('export function installWheelZoom(map)', 'window.installWheelZoom = function(map)')});
  const result = await page.evaluate(async () => {
    const map = L.map('map',{scrollWheelZoom:false,zoomAnimation:false,minZoom:3,maxZoom:19,zoomSnap:1}).setView([0,0],10);
    installWheelZoom(map);
    const wait = ms => new Promise(resolve => setTimeout(resolve,ms));
    const scale = Math.abs(L.DomEvent.getWheelDelta(new WheelEvent('wheel', {deltaY:1,deltaMode:0})));
    const send = (deltaY, ctrlKey=false, deltaMode=0) => map.getContainer().dispatchEvent(new WheelEvent('wheel',{deltaY:deltaMode === 0 ? deltaY / scale : deltaY,ctrlKey,deltaMode,clientX:400,clientY:300,bubbles:true,cancelable:true}));
    const results = {};
    map.getContainer().dispatchEvent(new WheelEvent('wheel',{deltaY:-1,deltaMode:0,bubbles:true,cancelable:true})); await wait(120); results.tiny=map.getZoom();
    send(-300); results.immediate=map.getZoom(); send(-960);send(300);results.latched=map.getZoom();
    await wait(120);send(300);results.opposite=map.getZoom();await wait(120);
    send(-960);results.freshHuge=map.getZoom();await wait(120);map.setZoom(10);
    send(-20);send(25);results.preThresholdReversal=map.getZoom();send(75);results.reversedThreshold=map.getZoom();await wait(120);
    send(-1,true);results.pinchBelow=map.getZoom();send(-100,true);results.pinch=map.getZoom();await wait(120);
    send(-30);send(-6,true);results.modeReset=map.getZoom();await wait(120);
    send(-30);map.panBy([20,0],{animate:false});send(-15);results.externalReset=map.getZoom();await wait(120);
    map.setZoom(19);send(-960);send(960);results.max=map.getZoom();await wait(120);send(300);results.afterMax=map.getZoom();
    map.setZoom(3);send(960);results.min=map.getZoom();await wait(120);send(-300);results.afterMin=map.getZoom();
    await wait(120);send(-4,false,1);results.lineMode=map.getZoom();
    map.remove();send(-300);results.destroyClean=true;
    return results;
  });
  assert.deepEqual(result,{tiny:10,immediate:11,latched:11,opposite:10,freshHuge:11,preThresholdReversal:10,reversedThreshold:9,pinchBelow:9,pinch:10,modeReset:10,externalReset:10,max:19,afterMax:18,min:3,afterMin:4,lineMode:5,destroyClean:true});
  const report={passed:true,kind:'Synthetic DOM WheelEvents through production handler and Leaflet normalization; no physical hardware claim',result};
  console.log(JSON.stringify(report,null,2));
} finally { await browser.close(); }
