#!/usr/bin/env node
// A bounded SVG -> native DrawingML bridge. Unsupported appearance fails preflight.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {spawnSync} from 'node:child_process';
const require=createRequire(import.meta.url);
function dependency(name){
  try{return require.resolve(name);}
  catch(e){
    const base=process.env.RUNTIME_NODE_MODULES||process.env.NODE_PATH?.split(path.delimiter)[0];
    if(!base)throw new Error('Set RUNTIME_NODE_MODULES (or NODE_PATH) to the existing package directory.');
    return createRequire(path.join(base,'__vector_runtime__.cjs')).resolve(name);
  }
}
const args=process.argv.slice(2), help='Usage: node svg_to_pptx.mjs input.svg --out NEW_BUILD_DIR --browser /path/to/chrome [--width 1280] [--python python3]\nRequires playwright and @oai/artifact-tool. Creates candidate.pptx, scene.json, source.png and structure.json. Run the presentation finalizer and render the actual PPTX before delivery.';
if(args.includes('--help')||!args.length){console.log(help);process.exit(0);}
const input=path.resolve(args.shift()), opts={width:1280,python:'python3'};
while(args.length){
  const key=args.shift();
  if(!['--out','--browser','--width','--python'].includes(key)||!args.length)throw new Error(help);
  opts[key.slice(2)]=args.shift();
}
if(!opts.out||!opts.browser||(!Number.isFinite(+opts.width)||!(+opts.width>0)))throw new Error(help);
const out=path.resolve(opts.out);
await fs.mkdir(out,{recursive:false});
const xml=await fs.readFile(input,'utf8');
if(/<!DOCTYPE|<!ENTITY/i.test(xml))throw new Error('DTD/entities are unsupported.');
const browserModule=await import(pathToFileURL(dependency('playwright')).href);
const {chromium}=browserModule.chromium?browserModule:browserModule.default;
const browser=await chromium.launch({executablePath:opts.browser,headless:true});
let scene;
try{
 const page=await browser.newPage();
 await page.route('**/*',route=>route.abort());
 scene=await page.evaluate(async ({xml,width})=>{
  const doc=new DOMParser().parseFromString(xml,'image/svg+xml'),root=doc.documentElement;
  if(doc.querySelector('parsererror')||root.localName!=='svg')throw new Error('Invalid SVG.');
  const allowed=new Set(['svg','g','defs','title','desc','path','rect','circle','ellipse','line','polyline','polygon','text','linearGradient','stop']);
  const seen=new Set();
  for(const n of [root,...root.querySelectorAll('*')]){
   if(!allowed.has(n.localName))throw new Error('Unsupported element: '+n.localName+' #'+n.id);
   for(const a of n.attributes)if(/^on/i.test(a.name)||a.localName==='href')throw new Error('Unsupported event/reference on #'+n.id);
   if(n.id){if(seen.has(n.id))throw new Error('Duplicate ID: '+n.id);seen.add(n.id);}
   if(n.localName==='svg'&&n!==root)throw new Error('Flatten nested SVG viewports first.');
  }
  document.body.style.margin='0';
  document.body.append(document.importNode(root,true));
  const svg=document.querySelector('svg'),v=svg.viewBox.baseVal;
  if(!(v.width>0&&v.height>0))throw new Error('An explicit positive viewBox is required.');
  const height=width*v.height/v.width,scale=width/v.width;
  svg.setAttribute('width',width);svg.setAttribute('height',height);
  svg.style.display='block';document.body.style.background='white';
  await document.fonts.ready;
  const normalize=new DOMMatrix([scale,0,0,scale,-v.x*scale,-v.y*scale]);
  const inv=svg.getScreenCTM().inverse(),items=[],groups={},warnings=[];
  let auto=0;
  const fail=(n,what)=>{throw new Error(what+' (#'+(n.id||n.localName)+')');};
  const num=(n,k,d=0)=>{const raw=n.getAttribute(k);if(raw==null)return d;if(!/^[-+]?([0-9]*\.)?[0-9]+(e[-+]?[0-9]+)?$/i.test(raw.trim()))fail(n,'Use unitless numeric '+k);return Number(raw);};
  const plainColor=(n,c)=>{if(c==='none')return c;const m=c.match(/^rgba?\(([^)]+)\)$/);if(!m)fail(n,'Unsupported color '+c);const a=m[1].split(/[,\s]+/).map(Number);if(a.length>3&&a[3]!==1)fail(n,'Normalize transparent paint first');return '#'+a.slice(0,3).map(v=>Math.round(v).toString(16).padStart(2,'0')).join('');};
  function paint(n,c,rotation){
   if(!c.startsWith('url('))return plainColor(n,c);
   const id=c.match(/#([^)"']+)/)?.[1],g=id&&document.getElementById(id);
   if(!g||g.localName!=='linearGradient')fail(n,'Only local axial linear gradients are supported');
   if((g.getAttribute('gradientUnits')||'objectBoundingBox')!=='objectBoundingBox'||g.hasAttribute('gradientTransform')||(g.getAttribute('spreadMethod')||'pad')!=='pad')fail(n,'Normalize gradient coordinates first');
   const val=(key,d)=>{const s=g.getAttribute(key);return s==null?d:s.endsWith('%')?parseFloat(s)/100:Number(s);};
   const x1=val('x1',0),y1=val('y1',0),x2=val('x2',1),y2=val('y2',0);
   const valid=(x1===x2&&Math.min(y1,y2)===0&&Math.max(y1,y2)===1)||(y1===y2&&Math.min(x1,x2)===0&&Math.max(x1,x2)===1);
   if(!valid)fail(n,'Only full-span horizontal/vertical gradients are supported');
   const stops=[...g.children].filter(s=>s.localName==='stop').map(s=>{
    const st=getComputedStyle(s);if(+st.stopOpacity!==1)fail(n,'Transparent gradient stops are unsupported');
    const o=s.getAttribute('offset')||'0',f=o.endsWith('%')?parseFloat(o)/100:Number(o);
    if(!Number.isFinite(f)||f<0||f>1)fail(n,'Invalid gradient stop');
    return {offset:Math.round(f*100000),color:plainColor(n,st.stopColor)};
   });
   if(stops.length<2||stops.some((s,i)=>i&&s.offset<stops[i-1].offset))fail(n,'Gradient stops must be ordered');
   return {type:'gradient',gradientKind:'linear',angleDeg:(Math.atan2(y2-y1,x2-x1)*180/Math.PI+rotation+360)%360,stops};
  }
  function pathCommands(n,d){
   const tokens=d.match(/[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g)||[];
   if(d.replace(/[a-zA-Z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?|[\s,]/g,''))fail(n,'Malformed path data');
   let i=0,res=[];
   while(i<tokens.length){
    const op=tokens[i++],count={M:2,L:2,C:6,Z:0}[op];
    if(count===undefined)fail(n,'Normalize path to explicit absolute M/L/C/Z commands');
    const v=tokens.slice(i,i+count).map(Number);i+=count;
    if(v.length!==count||v.some(x=>!Number.isFinite(x)))fail(n,'Incomplete path command');
    res.push([op,...v]);
   }
   if(res[0]?.[0]!=='M')fail(n,'Path must begin with M');
   return res;
  }
  function rect(n){
   const x=num(n,'x'),y=num(n,'y'),w=num(n,'width'),h=num(n,'height');
   if(w<=0||h<=0)fail(n,'Rectangle has nonpositive dimensions');
   const rx=Math.min(num(n,'rx',num(n,'ry')),w/2),ry=Math.min(num(n,'ry',num(n,'rx')),h/2),k=.5522847498;
   if(rx<0||ry<0)fail(n,'Negative corner radius');
   return [['M',x+rx,y],['L',x+w-rx,y],['C',x+w-rx+k*rx,y,x+w,y+ry-k*ry,x+w,y+ry],['L',x+w,y+h-ry],['C',x+w,y+h-ry+k*ry,x+w-rx+k*rx,y+h,x+w-rx,y+h],['L',x+rx,y+h],['C',x+rx-k*rx,y+h,x,y+h-ry+k*ry,x,y+h-ry],['L',x,y+ry],['C',x,y+ry-k*ry,x+rx-k*rx,y,x+rx,y],['Z']];
  }
  function visit(n,anc=[]){
   const tag=n.localName;
   if(['defs','title','desc'].includes(tag))return;
   const st=getComputedStyle(n);
   if(st.display==='none')return;
   if(st.visibility!=='visible'&&!['g','svg'].includes(tag))return;
   if(+st.opacity!==1||+st.fillOpacity!==1||+st.strokeOpacity!==1)fail(n,'Normalize opacity before native conversion');
   for(const key of ['clipPath','mask','filter','markerStart','markerMid','markerEnd'])if(st[key]&&st[key]!=='none')fail(n,'Unsupported '+key+'; expand explicitly before conversion');
   if(st.mixBlendMode&&st.mixBlendMode!=='normal')fail(n,'Blend modes are unsupported');
   if(st.vectorEffect&&st.vectorEffect!=='none')fail(n,'Non-scaling stroke is unsupported');
   if(st.strokeDasharray!=='none')fail(n,'Expand dashed strokes first');
   if(!['round','square','butt'].includes(st.strokeLinecap)||!['round','miter','bevel'].includes(st.strokeLinejoin))fail(n,'Unsupported stroke cap/join');
   if(st.paintOrder&&st.paintOrder!=='normal'&&st.paintOrder!=='fill stroke')fail(n,'Normalize paint order first');
   if(!n.id){do{n.id='native-'+(++auto);}while(seen.has(n.id));seen.add(n.id);}
   if(tag==='svg'||tag==='g'){
    if(tag==='g')groups[n.id]={id:n.id,parent:anc.at(-1)||null,edit_unit:n.dataset.editUnit==='true'};
    for(const c of n.children)visit(c,tag==='g'?[...anc,n.id]:anc);
    return;
   }
   const m=normalize.multiply(inv.multiply(n.getScreenCTM())),sx=Math.hypot(m.a,m.b),sy=Math.hypot(m.c,m.d);
   if(sx<1e-9||Math.abs(sx-sy)>1e-6||Math.abs(m.a*m.c+m.b*m.d)>1e-6||m.a*m.d-m.b*m.c<=0)fail(n,'Normalize skew, reflection or nonuniform transforms first');
   const rotation=Math.atan2(m.b,m.a)*180/Math.PI;
   const pt=(x,y)=>{const p=new DOMPoint(x,y).matrixTransform(m);return [p.x,p.y];};
   const it={id:n.id,groups:anc,tag,fill:paint(n,st.fill,rotation),stroke:plainColor(n,st.stroke),lineWidth:parseFloat(st.strokeWidth)*sx,lineCap:st.strokeLinecap,lineJoin:st.strokeLinejoin,miterLimit:parseFloat(st.strokeMiterlimit)};
   if(st.fillRule==='evenodd'&&st.fill!=='none')fail(n,'Normalize evenodd compound fills before conversion');
   if(tag==='text'){
    if(n.children.length||n.hasAttribute('textLength')||n.hasAttribute('lengthAdjust'))fail(n,'Split rich text into simple text objects');
    for(const key of ['x','y','dx','dy'])if(n.hasAttribute(key))num(n,key);
    if(st.direction!=='ltr'||st.textTransform!=='none'||st.fontVariantCaps!=='normal')fail(n,'Normalize text direction/case first');
    if(n.hasAttribute('rotate')||st.writingMode!=='horizontal-tb'||!['0px','normal'].includes(st.letterSpacing)||!['0px','normal'].includes(st.wordSpacing)||st.textDecorationLine!=='none')fail(n,'Unsupported text layout');
    if(typeof it.fill!=='string'||it.stroke!=='none')fail(n,'Text needs a solid fill and no outline');
    const fontSize=parseFloat(st.fontSize),b=n.getBBox(),[cx,cy]=pt(b.x+b.width/2,b.y+b.height/2);
    if(!n.textContent.trim())return;
    const family=st.fontFamily.split(',')[0].trim().replace(/^["']|["']$/g,'');
    const w=(b.width+6)*sx,h=Math.max(b.height+2,fontSize*1.24)*sx;
    Object.assign(it,{text:n.textContent,fontSize:fontSize*sx,typeface:family,bold:Number(st.fontWeight)>=600,italic:st.fontStyle==='italic',rotation,x:cx-w/2,y:cy-h/2,width:w,height:h});
   }else if(tag==='ellipse'||tag==='circle'){
    const [cx,cy]=pt(num(n,'cx'),num(n,'cy')),rx=num(n,tag==='circle'?'r':'rx')*sx,ry=num(n,tag==='circle'?'r':'ry')*sx;
    if(rx<=0||ry<=0)fail(n,'Nonpositive ellipse radius');
    Object.assign(it,{geometry:'ellipse',x:cx-rx,y:cy-ry,width:2*rx,height:2*ry,rotation});
    // Native ellipse rotation already rotates its local gradient.
    if(typeof it.fill==='object')it.fill.angleDeg=(it.fill.angleDeg-rotation+360)%360;
   }else{
    let cs;
    if(tag==='path')cs=pathCommands(n,n.getAttribute('d')||'');
    else if(tag==='rect')cs=rect(n);
    else if(tag==='line')cs=[['M',num(n,'x1'),num(n,'y1')],['L',num(n,'x2'),num(n,'y2')]];
    else if(['polyline','polygon'].includes(tag)){
     const raw=n.getAttribute('points')||'',pts=raw.trim().split(/[\s,]+/).map(Number);
     if(pts.length<4||pts.length%2||pts.some(v=>!Number.isFinite(v)))fail(n,'Invalid points');
     cs=[];for(let i=0;i<pts.length;i+=2)cs.push([i?'L':'M',pts[i],pts[i+1]]);
     if(tag==='polygon')cs.push(['Z']);
    }else fail(n,'Unexpected visible '+tag);
    const transformed=cs.map(c=>[c[0],...c.slice(1).reduce((a,v,i,arr)=>i%2?a:[...a,...pt(v,arr[i+1])],[])]);
    const xs=[],ys=[];for(const c of transformed)for(let i=1;i<c.length;i+=2){xs.push(c[i]);ys.push(c[i+1]);}
    const x=Math.min(...xs),y=Math.min(...ys),w=Math.max(.01,Math.max(...xs)-x),h=Math.max(.01,Math.max(...ys)-y);
    const commands=transformed.map(c=>{
     if(c[0]==='Z')return {close:{}};
     const p=c.slice(1).map((v,i)=>v-(i%2?y:x));
     if(c[0]==='C')return {cubicBezTo:Object.fromEntries(['x1','y1','x2','y2','x','y'].map((k,i)=>[k,p[i]]))};
     return {[c[0]==='M'?'moveTo':'lineTo']:{x:p[0],y:p[1]}};
    });
    Object.assign(it,{geometry:'custom',x,y,width:w,height:h,commands});
   }
   items.push(it);
  }
  visit(svg);
  if(!items.length)throw new Error('No visible editable objects.');
  warnings.push('Text box metrics vary by renderer; inspect actual PPTX output. Arrows remain paths, not automatically attached connectors.');
  return {version:1,canvas:[width,height],viewBox:[v.x,v.y,v.width,v.height],items,groups,warnings};
 },{xml,width:+opts.width});
 await page.setViewportSize({width:Math.ceil(scene.canvas[0]),height:Math.ceil(scene.canvas[1])});
 await page.screenshot({path:path.join(out,'source.png')});
}finally{await browser.close();}
scene.source=input;
await fs.writeFile(path.join(out,'scene.json'),JSON.stringify(scene,null,2));
const artifactModule=await import(pathToFileURL(dependency('@oai/artifact-tool')).href);
const {Presentation,PresentationFile}=artifactModule.Presentation?artifactModule:artifactModule.default;
const deck=Presentation.create({slideSize:{width:scene.canvas[0],height:scene.canvas[1]}});
const slide=deck.slides.add();slide.background.fill='#ffffff';
for(const it of scene.items){
 const options={name:it.id,geometry:it.geometry||'textbox',position:{left:it.x,top:it.y,width:it.width,height:it.height,rotation:it.rotation||0},fill:it.tag==='text'?'none':it.fill,line:{style:'solid',fill:it.stroke,width:it.lineWidth}};
 if(it.commands)options.customPaths=[{width:it.width,height:it.height,commands:it.commands}];
 const shape=slide.shapes.add(options);
 if(it.tag==='text'){shape.text=it.text;shape.text.style={typeface:it.typeface,fontSize:it.fontSize,bold:it.bold,italic:it.italic,color:it.fill,alignment:'center',verticalAlignment:'middle',wrap:'none',autoFit:'none',insets:0};}
}
await (await PresentationFile.exportPptx(deck)).save(path.join(out,'ungrouped.pptx'));
const result=spawnSync(opts.python,[path.join(import.meta.dirname,'pptx_native_groups.py'),'--scene',path.join(out,'scene.json'),'--input',path.join(out,'ungrouped.pptx'),'--output',path.join(out,'candidate.pptx'),'--stats',path.join(out,'structure.json')],{encoding:'utf8'});
if(result.status!==0)throw new Error(result.stderr||result.stdout||String(result.error));
console.log(result.stdout.trim());
