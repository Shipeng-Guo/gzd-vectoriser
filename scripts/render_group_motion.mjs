#!/usr/bin/env node
/** Render real SVG edit-unit translations. Requires Playwright and sharp.
 * Root-coordinate movement; source never rewritten. See group-motion.md. */
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require('playwright'), sharp=require('sharp');
const args=process.argv.slice(2), opt=k=>args[args.indexOf(k)+1];
if(args.includes('--help') || !args.includes('--svg') || !args.includes('--config') || !args.includes('--out')) {
 console.log('node render_group_motion.mjs --svg drawing.svg --config motion.json --out NEW_DIR [--browser /path/to/chrome] [--keyframes-only]\nConfiguration: canvas [w,h], fps, scenes [{title, caption, viewBox:[x,y,w,h], moves:[{id,delta:[dx,dy]} | {childrenOf,radial:{center:[x,y],distance}}], watch:[id], travel_seconds, hold_seconds, rest_seconds}].');
 process.exit(args.includes('--help')?0:1);
}
const input=path.resolve(opt('--svg')), cfg=JSON.parse(fs.readFileSync(opt('--config'),'utf8')), out=path.resolve(opt('--out'));
if(fs.existsSync(out)) throw Error('Use a new output directory.');
const hash=b=>createHash('sha256').update(b).digest('hex');
const raw=fs.readFileSync(input), sourceHash=hash(raw), [W,H]=cfg.canvas||[1200,1060];
if(![W,H].every(n=>Number.isInteger(n)&&n>=200&&n<=4096))throw Error('Canvas must be integers 200..4096.');
if(!Array.isArray(cfg.scenes)||!cfg.scenes.length)throw Error('Nonempty scenes required.');
const fps=cfg.fps??20;if(!Number.isFinite(fps)||fps<1||fps>50)throw Error('fps must be 1..50.');
const ms=Math.max(20,Math.round(1000/fps/10)*10), header=cfg.header_height??104, footer=cfg.footer_height??50;
if(header<0||footer<0||header+footer>=H)throw Error('Invalid header/footer height.');
fs.mkdirSync(out,{recursive:true});fs.mkdirSync(path.join(out,'frames'));
fs.writeFileSync(path.join(out,'source.svg'),raw);fs.writeFileSync(path.join(out,'motion.json'),JSON.stringify(cfg,null,2));
let browser;
try {
 browser=await chromium.launch({headless:true,...(args.includes('--browser')?{executablePath:opt('--browser')}:{})});
 const page=await browser.newPage({viewport:{width:W,height:H},deviceScaleFactor:1});
 await page.setContent(`<!doctype html><meta charset="utf-8"><style>*{box-sizing:border-box}body{margin:0;background:white;color:#183d42;font-family:Arial,'Arial Unicode MS',sans-serif}header{height:${header}px;padding:16px 26px;background:#edf4f2;border-bottom:1px solid #d5e3df}h1{margin:0;font-size:26px;line-height:36px}p{margin:3px 0;font-size:18px;color:#48666b}#stage{height:${H-header-footer}px;width:${W}px}#stage>svg{width:100%;height:100%;display:block}footer{height:${footer}px;padding:12px 26px;background:#edf4f2;display:flex;justify-content:space-between;font-size:17px}</style><header><h1></h1><p></p></header><div id="stage"></div><footer><span id="phase"></span><span id="step"></span></footer>`);
 await page.evaluate(xml=>{
  const doc=new DOMParser().parseFromString(xml,'image/svg+xml');
  if(doc.querySelector('parsererror')||doc.documentElement.localName!=='svg')throw Error('Invalid SVG');
  if(doc.querySelector('script,foreignObject,animate,animateTransform,set'))throw Error('Active SVG content is unsupported.');
  for(const e of doc.querySelectorAll('*'))for(const a of e.attributes){if(a.name.toLowerCase().startsWith('on'))throw Error('Event attributes unsupported');if(['href','xlink:href'].includes(a.name)&&!a.value.startsWith('#')&&!a.value.startsWith('data:'))throw Error('External references must be made self-contained');}
  document.getElementById('stage').append(document.importNode(doc.documentElement,true));
  window.art=document.querySelector('#stage>svg');art.setAttribute('preserveAspectRatio','xMidYMid meet');
 },raw.toString());
 await page.evaluate(()=>document.fonts.ready);
 const frames=[], scenes=[];
 async function saveFrame(scene,index,t,duration,phase) {
  const data=await page.evaluate(({t,phase,index,total})=>{
   document.getElementById('phase').textContent=phase;document.getElementById('step').textContent=`${index+1} / ${total}`;
   for(const m of window.motion){if(t===0){m.original===null?m.el.removeAttribute('transform'):m.el.setAttribute('transform',m.original);}else{m.el.setAttribute('transform',`translate(${m.local[0]*t} ${m.local[1]*t}) ${m.original||''}`)}}
   // Rebuild the SVG display list to avoid stale repaint antialiasing after hide/move.
   const host=art.parentNode;art.remove();host.appendChild(art);
   const rect=e=>{const b=e.getBoundingClientRect();return [b.x,b.y,b.width,b.height]};
   return {moved:motion.map(m=>({id:m.id,box:rect(m.el),delta:m.delta,original:m.original,members:[...m.el.children].map(e=>e.id).filter(Boolean)})),watch:window.watches.map(e=>({id:e.id,box:rect(e)}))};
  },{t,phase,index,total:cfg.scenes.length});
  const file=`frames/${String(frames.length).padStart(5,'0')}.png`;
  await page.screenshot({path:path.join(out,file)});
  frames.push({file,duration_ms:duration,scene:index,position:t});return {file,...data};
 }
 for(let i=0;i<cfg.scenes.length;i++) {
  const s=cfg.scenes[i];if(!Array.isArray(s.viewBox)||s.viewBox.length!==4||!s.viewBox.every(Number.isFinite)||s.viewBox[2]<=0||s.viewBox[3]<=0)throw Error('Invalid scene viewBox');
  for(const k of ['travel_seconds','hold_seconds','rest_seconds'])if(s[k]!==undefined&&(!Number.isFinite(s[k])||s[k]<0))throw Error('Invalid timing');
  const setup=await page.evaluate(s=>{
   document.querySelector('h1').textContent=s.title||'';document.querySelector('header p').textContent=s.caption||'';
   art.setAttribute('viewBox',s.viewBox.join(' '));
   const get=id=>{const hits=[...art.querySelectorAll('[id]')].filter(e=>e.id===id);if(hits.length!==1)throw Error('Missing or nonunique ID: '+id);return hits[0]};
   const rect=e=>{const b=e.getBoundingClientRect();return [b.x,b.y,b.width,b.height]};
   // Optional scene isolation: preserve source groups/ancestors, hide unrelated branches.
   window.hiddenStyles=[];
   if(s.retain){const keep=s.retain.map(get);const walk=e=>{if(['defs','style','title','desc','metadata'].includes(e.localName))return;if(keep.includes(e))return;if(keep.some(k=>e.contains(k))){for(const c of e.children)walk(c)}else{hiddenStyles.push([e,e.getAttribute('style')]);e.style.display='none'}};for(const e of art.children)walk(e);}
   const expanded=[];
   for(const spec of s.moves||[]) {
    if(spec.childrenOf) {
     if(!spec.radial||!Array.isArray(spec.radial.center)||spec.radial.center.length!==2||!spec.radial.center.every(Number.isFinite)||!Number.isFinite(spec.radial.distance))throw Error('Invalid radial specification');
     for(const el of get(spec.childrenOf).children) {
      if(el.localName!=='g'||!el.id)throw Error('childrenOf requires immediate named g children');
      const b=el.getBBox(),c=new DOMPoint(b.x+b.width/2,b.y+b.height/2).matrixTransform(art.getScreenCTM().inverse().multiply(el.getScreenCTM()));
      const dx=c.x-spec.radial.center[0],dy=c.y-spec.radial.center[1],length=Math.hypot(dx,dy)||1;
      expanded.push({id:el.id,delta:[dx/length*spec.radial.distance,dy/length*spec.radial.distance]});
     }
    } else expanded.push(spec);
   }
   if(!expanded.length)throw Error('No moved objects');
   window.motion=expanded.map(m=>{const el=get(m.id);if(el.localName!=='g')throw Error('Animate semantic g units, not path fragments: '+m.id);if(!Array.isArray(m.delta)||m.delta.length!==2||!m.delta.every(Number.isFinite))throw Error('Invalid delta');
    const mat=art.getScreenCTM().inverse().multiply(el.parentElement.getScreenCTM()).inverse();
    const local=[mat.a*m.delta[0]+mat.c*m.delta[1],mat.b*m.delta[0]+mat.d*m.delta[1]];
    return {...m,el,original:el.getAttribute('transform'),local,old:rect(el)};
   });
   for(let j=0;j<motion.length;j++)for(let k=j+1;k<motion.length;k++)if(motion[j].el.contains(motion[k].el)||motion[k].el.contains(motion[j].el))throw Error('Overlapping or duplicate moved units');
   window.watches=(s.watch||[]).map(get);
   if(!watches.length)throw Error('Declare at least one static underlay/watch ID per scene');
   if(watches.some(w=>motion.some(m=>m.el.contains(w)||w.contains(m.el))))throw Error('Watch must be independent of moved units');
   const cm=art.getScreenCTM();return {moves:motion.map(({id,delta,local,old,original})=>({id,delta,local,old,original})),watch:watches.map(e=>({id:e.id,box:rect(e)})),matrix:[cm.a,cm.b,cm.c,cm.d]};
  },s);
  const label={...(cfg.labels||{}),...(s.labels||{})}, rest=Math.max(ms,Math.round((s.rest_seconds??.8)*100)*10), hold=Math.max(ms,Math.round((s.hold_seconds??2)*100)*10);
  const steps=args.includes('--keyframes-only')?1:Math.max(2,Math.round((s.travel_seconds??1.5)*1000/ms));
  const start=await saveFrame(s,i,0,rest,label.assembled||'Assembled · complete composition');let peak;
  for(let j=1;j<=steps;j++){const t=(1-Math.cos(Math.PI*j/steps))/2;const f=await saveFrame(s,i,t,j===steps?hold:ms,j===steps?(label.exploded||'Exploded hold · inspect the underlay'):(label.moving||'Moving existing groups apart'));if(j===steps)peak=f;}
  for(let j=1;j<=steps;j++){const t=j===steps?0:(1+Math.cos(Math.PI*j/steps))/2;await saveFrame(s,i,t,j===steps?rest:ms,j===steps?(label.returned||'Restored · original composition'):(label.returning||'Returning groups to position'));}
  const end=frames.at(-1);
  // Compare artwork only: captions intentionally change at endpoint.
  const ar=await sharp(path.join(out,start.file)).extract({left:0,top:header,width:W,height:H-header-footer}).raw().toBuffer();
  const br=await sharp(path.join(out,end.file)).extract({left:0,top:header,width:W,height:H-header-footer}).raw().toBuffer();
  const maxErr=Math.max(...setup.moves.map(m=>{const q=peak.moved.find(x=>x.id===m.id).box,ct=setup.matrix;return Math.max(Math.abs(q[0]-m.old[0]-ct[0]*m.delta[0]-ct[2]*m.delta[1]),Math.abs(q[1]-m.old[1]-ct[1]*m.delta[0]-ct[3]*m.delta[1]));}));
  const watchesUnchanged=setup.watch.every(w=>w.box.every((n,j)=>Math.abs(n-peak.watch.find(x=>x.id===w.id).box[j])<.02));
  const clipping=peak.moved.filter(m=>m.box[0]<0||m.box[1]<header||m.box[0]+m.box[2]>W||m.box[1]+m.box[3]>H-footer).map(m=>m.id);
  const record={title:s.title,...setup,peak,restored_pixels_equal:ar.equals(br),watch_unchanged:watchesUnchanged,max_screen_delta_error:maxErr,clipped_at_peak:clipping};
  scenes.push(record);
  if(!record.restored_pixels_equal||!watchesUnchanged||maxErr>.05||clipping.length)throw Error('Motion verification failed: '+JSON.stringify({scene:s.title,restored:record.restored_pixels_equal,watchesUnchanged,maxErr,clipping}));
  await page.evaluate(()=>{for(const [e,style] of window.hiddenStyles)style===null?e.removeAttribute('style'):e.setAttribute('style',style)});
  console.log(JSON.stringify({scene:i+1,title:s.title,moved:setup.moves.length,restored:true}));
 }
 if(hash(fs.readFileSync(input))!==sourceHash)throw Error('Input modified');
 const manifest={source:input,source_sha256:sourceHash,canvas:[W,H],fps:1000/ms,art_box:[0,header,W,H-header-footer],frames,scenes,source_unchanged:true,scope:'Actual SVG g transforms only. Tests cover declared static objects, root-coordinate displacement, no peak clipping, and exact restored artwork. Inspect exposed underlays separately.'};
 fs.writeFileSync(path.join(out,'frames.json'),JSON.stringify(manifest,null,2));
} finally {if(browser)await browser.close()}
