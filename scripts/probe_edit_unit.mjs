#!/usr/bin/env node
/** Read-only SVG edit probe. Requires Playwright and sharp. It checks ownership
 * and rendered displacement, not semantic correctness or an editor's click UX. */
import fs from 'node:fs';import {createHash} from 'node:crypto';import path from 'node:path';import {pathToFileURL} from 'node:url';import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);const {chromium}=require('playwright');const sharp=require('sharp');
const a=process.argv.slice(2);const opt=k=>{const i=a.indexOf(k);return i<0?null:a[i+1]};
if(a.includes('--help')||!a[0]||!opt('--cases')||!opt('--out')){console.log('node probe_edit_unit.mjs drawing.svg --cases cases.json --out NEW_DIR [--browser /path/to/chrome] [--pixel-tolerance 0] [--pixel-renderer browser|sharp]\ncases: [{id, delta:[dx,dy], watch:[nearbyExternalId,...], members?:[requiredDescendantId,...], margin?:8}]\nAlways read back moved/hidden screenshots; bounds checks cannot judge underlay shape.');process.exit(a.includes('--help')?0:1)}
const svg=path.resolve(a[0]),out=path.resolve(opt('--out')),cases=JSON.parse(fs.readFileSync(opt('--cases'),'utf8'));
if(fs.existsSync(out))throw Error('Use a new output directory to retain prior evidence');
if(!Array.isArray(cases)||!cases.length)throw Error('Nonempty cases array required');
for(const c of cases)if(typeof c.id!=='string'||!Array.isArray(c.delta)||c.delta.length!==2||!c.delta.every(Number.isFinite)||!Array.isArray(c.watch)||!c.watch.length||c.watch.includes(c.id))throw Error('Each case requires id, finite delta and distinct neighboring watch IDs');
for(const c of cases)if(c.members!==undefined&&(!Array.isArray(c.members)||!c.members.length||c.members.some(id=>typeof id!=='string'||!id)))throw Error('members, when supplied, must be a nonempty ID array');
const tolerance=Number(opt("--pixel-tolerance")??0);if(!Number.isInteger(tolerance)||tolerance<0||tolerance>2)throw Error("pixel-tolerance must be an integer 0..2; exact changed pixels remain recorded");
const pixelRenderer=opt('--pixel-renderer')||'browser';if(!['browser','sharp'].includes(pixelRenderer))throw Error('pixel-renderer must be browser or sharp');
const sourceHash=createHash('sha256').update(fs.readFileSync(svg)).digest('hex');
fs.mkdirSync(out,{recursive:true});let browser;
try{
 browser=await chromium.launch({headless:true,...(opt('--browser')?{executablePath:opt('--browser')}:{})});const page=await browser.newPage({viewport:{width:1200,height:900},deviceScaleFactor:1});await page.goto(pathToFileURL(svg).href);await page.evaluate(()=>document.fonts.ready);
 const dims=await page.evaluate(()=>{const s=document.documentElement;if(s.localName!=='svg')throw Error('Standalone SVG required');const b=s.viewBox.baseVal;let w=b.width||Number(s.getAttribute('width')),h=b.height||Number(s.getAttribute('height'));if(!(w>0&&h>0&&w<=10000&&h<=10000))throw Error('Invalid/oversized canvas');s.setAttribute('width',w);s.setAttribute('height',h);return [Math.ceil(w),Math.ceil(h)]});await page.setViewportSize({width:dims[0],height:dims[1]});
 // Reload after setting the final viewport: avoid comparing a cached initial-size raster.
 await page.reload();await page.evaluate(async ([w,h])=>{let s=document.documentElement;s.setAttribute('width',w);s.setAttribute('height',h);await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))},dims);
 const baseline=await page.locator('svg').first().screenshot();fs.writeFileSync(path.join(out,'baseline.png'),baseline);const browserRaw0=await sharp(baseline).ensureAlpha().raw().toBuffer({resolveWithObject:true});let raw0=browserRaw0;
 if(pixelRenderer==='sharp'){const xml=await page.evaluate(()=>new XMLSerializer().serializeToString(document.documentElement));const det=await sharp(Buffer.from(xml)).resize(dims[0],dims[1]).png().toBuffer();fs.writeFileSync(path.join(out,'deterministic-baseline.png'),det);raw0=await sharp(det).ensureAlpha().raw().toBuffer({resolveWithObject:true})}
 const records=[];
 const state=async c=>page.evaluate(c=>{const e=document.getElementById(c.id);if(!e)throw Error('Missing '+c.id);const rect=n=>{const r=n.getBoundingClientRect();return [r.x,r.y,r.width,r.height]};const m=e.parentElement.getScreenCTM();return {box:rect(e),transform:e.getAttribute('transform'),labels:[...e.querySelectorAll('text')].map(n=>n.textContent),parentMatrix:[m.a,m.b,m.c,m.d],members:(c.members||[]).map(id=>{const n=document.getElementById(id);return {id,exists:!!n,owned:!!n&&e.contains(n)}}),watched:c.watch.map(id=>{const n=document.getElementById(id);if(!n)throw Error('Missing watched '+id);return {id,box:rect(n)}})}},c);
 for(let i=0;i<cases.length;i++){
  const c=cases[i],before=await state(c);await page.evaluate(({c,t})=>document.getElementById(c.id).setAttribute('transform',`translate(${c.delta[0]} ${c.delta[1]}) ${t||''}`),{c,t:before.transform});const after=await state(c),stem=String(i+1).padStart(2,'0');
  const editedXml=await page.evaluate(()=>new XMLSerializer().serializeToString(document.documentElement));
  fs.writeFileSync(path.join(out,stem+'-moved.svg'),editedXml);
  const buf=await page.locator('svg').first().screenshot();fs.writeFileSync(path.join(out,stem+'-moved.png'),buf);
  let pixelBuffer=buf;
  if(pixelRenderer==='sharp'){pixelBuffer=await sharp(Buffer.from(editedXml)).resize(dims[0],dims[1]).png().toBuffer();fs.writeFileSync(path.join(out,stem+'-deterministic-moved.png'),pixelBuffer)}
  const m=before.parentMatrix,expected=[m[0]*c.delta[0]+m[2]*c.delta[1],m[1]*c.delta[0]+m[3]*c.delta[1]],actual=after.box.slice(0,2).map((v,k)=>v-before.box[k]);
  const watched=before.watched.map((v,k)=>({id:v.id,unchanged:v.box.every((x,j)=>Math.abs(x-after.watched[k].box[j])<.02),before:v.box,after:after.watched[k].box}));
  const raw=await sharp(pixelBuffer).ensureAlpha().raw().toBuffer(),browserRaw=await sharp(buf).ensureAlpha().raw().toBuffer();let outside=0,significantOutside=0,outsidePixels=[],browserOutside=[];const pad=c.margin??8,boxes=[before.box,after.box];for(let y=0;y<dims[1];y++)for(let x=0;x<dims[0];x++){
   if(boxes.some(([bx,by,w,h])=>x>=bx-pad&&x<=bx+w+pad&&y>=by-pad&&y<=by+h+pad))continue;
   const p=(y*dims[0]+x)*4;const browserDelta=Math.max(...[0,1,2,3].map(k=>Math.abs(browserRaw[p+k]-browserRaw0.data[p+k])));if(browserDelta)browserOutside.push([x,y,browserDelta]);const delta=Math.max(...[0,1,2,3].map(k=>Math.abs(raw[p+k]-raw0.data[p+k])));if(delta){outside++;outsidePixels.push([x,y,delta]);if(delta>tolerance)significantOutside++;}
  }
  const labelsUnchanged=JSON.stringify(before.labels)===JSON.stringify(after.labels),pass=actual.every((v,k)=>Math.abs(v-expected[k])<.02)&&watched.every(x=>x.unchanged)&&significantOutside===0&&labelsUnchanged&&before.members.every(n=>n.owned)&&after.members.every(n=>n.owned);
  await page.evaluate(({id,t})=>{const e=document.getElementById(id);t===null?e.removeAttribute('transform'):e.setAttribute('transform',t);e.style.display='none'},{id:c.id,t:before.transform});await page.locator('svg').first().screenshot({path:path.join(out,stem+'-hidden.png')});await page.evaluate(id=>document.getElementById(id).style.removeProperty('display'),c.id);
  records.push({id:c.id,pass,expected_delta:expected,actual_delta:actual,watched,changed_pixels_outside_neighborhoods:outside,pixel_tolerance:tolerance,pixel_renderer:pixelRenderer,browser_exact_outside_pixels:browserOutside,significant_outside_pixels:significantOutside,exact_outside_pixels:outsidePixels,labels_unchanged:labelsUnchanged,required_members_before:before.members,required_members_after:after.members,old_box:before.box,new_box:after.box,moved:stem+'-moved.png',hidden:stem+'-hidden.png'});
 }
 if(createHash('sha256').update(fs.readFileSync(svg)).digest('hex')!==sourceHash)throw Error('Input SVG changed during probe');
 const result={pass:records.every(x=>x.pass),svg,svg_sha256:sourceHash,canvas:dims,pixel_renderer:pixelRenderer,cases:records,scope:'SVG DOM ownership of explicitly declared members, screen bounds, plus pixels outside old/new neighborhoods using the declared renderer. Browser raw differences are always retained; sharp uses deterministic independent SVG rasterizations when browser display-list repaint noise is present. Reviewer must inspect old location, new location and hidden underlay. This is not Illustrator click testing.'};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({pass:result.pass,cases:records.map(({id,pass,changed_pixels_outside_neighborhoods})=>({id,pass,changed_pixels_outside_neighborhoods}))}));if(!result.pass)process.exitCode=2;
}catch(e){fs.writeFileSync(path.join(out,'error.txt'),String(e.stack));throw e}finally{if(browser)await browser.close()}
