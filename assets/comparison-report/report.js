'use strict';
const data=JSON.parse(document.getElementById('report-data').textContent);
const $=id=>document.getElementById(id);
const modes={full:'source',local:'source'};
let current=null;
const states={pass:'Recheck recorded as passed',allowed_difference:'Authorised difference',open:'Awaiting review',reviewing:'Under review',fix_required:'Revision required',uncertain:'Uncertain'};
const errors=new Set();
// All offline resources load eagerly, including offscreen process images. Consumers
// can await reportReady once, then inspect reportState after reference switches.
const pending=new Set(), generations=new WeakMap();
const reportState=window.reportState={status:'loading',pending:0,errors:[]};
let initialized=false, resolveReady;
window.reportReady=new Promise(resolve=>{resolveReady=resolve;});
function publish(){
  reportState.pending=pending.size;reportState.errors=Array.from(errors);
  reportState.status=!initialized||pending.size?'loading':errors.size?'error':'ready';
  document.documentElement.dataset.reportState=reportState.status;
  if(reportState.status!=='loading'&&resolveReady){resolveReady({...reportState});resolveReady=null;}
}
function error(message){errors.add(message);$('errors').hidden=false;$('errors').textContent=Array.from(errors).join('\n');publish();}
function text(id,value){$(id).textContent=value||'';}
function download(label,url){const a=document.createElement('a');a.textContent=label;a.href=url;a.download='';$('downloads').append(a);}
function setImage(img,path,dimensionKey=''){
  if(img.getAttribute('src')===path)return;
  const generation={};generations.set(img,generation);pending.add(generation);
  img.loading='eager';img.dataset.decodeState='loading';img.src=path;publish();
  let timeout;
  Promise.race([img.decode(),new Promise((_,reject)=>{timeout=setTimeout(()=>reject(new Error('decode timeout')),30000);})])
    .then(()=>{
      if(generations.get(img)!==generation)return;
      if(!img.naturalWidth||!img.naturalHeight)throw new Error('empty image');
      img.dataset.decodeState='ready';
      if(dimensionKey&&(img.naturalWidth!==data.canvas.width||img.naturalHeight!==data.canvas.height)){
        img.dataset.decodeState='error';
        error(dimensionKey+' dimensions do not match the canvas: '+img.naturalWidth+'×'+img.naturalHeight+'; regenerate images in the same coordinate system.');
      }
    }).catch(()=>{
      // Rapid reference changes can abort an old decode; only the current source
      // may report a failure. Every attempt still leaves the pending set.
      if(generations.get(img)!==generation)return;
      img.dataset.decodeState='error';error('Image could not be decoded, is missing, or timed out: '+path);
    }).finally(()=>{clearTimeout(timeout);pending.delete(generation);publish();});
}
text('title',data.title);document.title=data.title;text('summary',data.summary);
text('review-status',data.review.complete?'Review records and final rediscovery checks passed; use the wipe to inspect the actual reconstruction.':'Draft: Visual acceptance is incomplete.'+(data.review.reason?' '+data.review.reason:''));
$('review-status').classList.toggle('draft',!data.review.complete);
text('provenance','Template version '+data.template_version+' · Canvas '+data.canvas.width+' × '+data.canvas.height+' px · Built '+data.created_at);
download('Download SVG',data.files.final_svg);download('Source',data.files.source);download('Final render at source dimensions',data.files.final_render);
if(data.files.assets_zip)download('Download component assets',data.files.assets_zip);
if(data.files.before_render)download('Previous delivery render',data.files.before_render);
download('Check records',data.files.review_check);
if(data.files.exact_viewer){const link=document.createElement('a');link.textContent='All pixel differences · IDs and wipe viewer';link.href=data.files.exact_viewer;$('downloads').append(link);}
function wipe(kind){const value=Number($(kind+'-range').value);$(kind+'-over').style.clipPath=`inset(0 ${100-value}% 0 0)`;$(kind+'-divider').style.left=value+'%';text(kind+'-value',value+'%');$(kind+'-range').setAttribute('aria-valuetext','Reference '+value+'%, final '+(100-value)+'%');$(kind+'-label').hidden=value===0;$(kind+'-compare').querySelector('.tag.right').hidden=value===100;}
function setMode(kind,mode){if(mode==='before'&&!data.files.before_render)return;modes[kind]=mode;const path=mode==='before'?data.files.before_render:data.files.source;setImage($(kind+'-reference'),path);text(kind+'-label',mode==='before'?'Previous delivery':'Source');for(const m of ['source','before'])$(kind+'-'+m).setAttribute('aria-pressed',String(mode===m));}
for(const kind of ['full','local']){setImage($(kind+'-final'),data.files.final_svg);$(kind+'-range').addEventListener('input',()=>wipe(kind));$(kind+'-source').addEventListener('click',()=>setMode(kind,'source'));$(kind+'-before').addEventListener('click',()=>setMode(kind,'before'));$(kind+'-before').hidden=!data.files.before_render;setMode(kind,'source');wipe(kind);}
$('full-compare').style.aspectRatio=data.canvas.width+'/'+data.canvas.height;
$('show-markers').addEventListener('change',event=>$('markers').hidden=!event.target.checked);
function select(id,scroll=false){current=data.regions.find(region=>region.id===id);if(!current)return;const[x,y,right,bottom]=current.box_xyxy;const w=right-x,h=bottom-y;const ratio=w/h;$('local-compare').style.aspectRatio=w+'/'+h;$('local-compare').style.maxWidth=(460*ratio)+'px';for(const img of [$('local-final'),$('local-reference')])Object.assign(img.style,{width:(data.canvas.width/w*100)+'%',height:(data.canvas.height/h*100)+'%',left:(-x/w*100)+'%',top:(-y/h*100)+'%'});$('region-select').value=id;text('local-title',current.id+' / '+current.title);text('local-status',states[current.verdict]||'Status unconfirmed');text('local-summary',current.summary);text('local-note',current.note);text('local-box','Source pixel bounds: '+current.box_xyxy.join(', ')+' · Review ledger ID: '+current.ledger_id);document.querySelectorAll('[data-region]').forEach(button=>{const active=button.dataset.region===id;button.setAttribute('aria-pressed',String(active));button.classList.toggle('active',active);});if(scroll)$('inspection').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});}
for(const region of data.regions){const option=document.createElement('option');option.value=region.id;option.textContent=region.id+' · '+region.title;$('region-select').append(option);const marker=document.createElement('button');marker.type='button';marker.className='marker';marker.dataset.region=region.id;marker.setAttribute('aria-label','View '+region.id+' '+region.title);const[x,y,right,bottom]=region.box_xyxy;Object.assign(marker.style,{left:x/data.canvas.width*100+'%',top:y/data.canvas.height*100+'%',width:(right-x)/data.canvas.width*100+'%',height:(bottom-y)/data.canvas.height*100+'%'});const span=document.createElement('span');span.textContent=region.id;marker.append(span);marker.addEventListener('click',()=>select(region.id,true));$('markers').append(marker);}
$('region-select').addEventListener('change',event=>select(event.target.value));$('region-picker').hidden=!data.regions.length;$('region-select').disabled=!data.regions.length;$('local-card').hidden=!data.regions.length;$('regions-empty').hidden=!!data.regions.length;$('show-markers').disabled=!data.regions.length;if(data.regions.length)select(data.regions[0].id);
function list(id,items,empty){for(const item of(items.length?items:[empty])){const li=document.createElement('li');li.textContent=item;$(id).append(li);}}
list('allowed',data.allowed_changes,'No permitted differences are registered.');list('limitations',data.limitations,'No additional limitations are listed; this does not guarantee that there are no differences or that everything is correct.');
data.steps.forEach((step,index)=>{const article=document.createElement('article');article.className='card step';const number=document.createElement('div');number.className='step-number';number.textContent=String(index+1).padStart(2,'0');const title=document.createElement('h3');title.textContent=step.title;const detail=document.createElement('p');detail.textContent=step.detail;article.append(number,title,detail);if(step.image){const figure=document.createElement('figure');const img=document.createElement('img');img.alt=step.caption||step.title;setImage(img,step.image);const caption=document.createElement('figcaption');caption.textContent=step.caption||step.title;figure.append(img,caption);article.append(figure);}$('steps').append(article);});
// Validate raster alignment without downloading or modifying any image.
for(const key of ['source','final_render','before_render'])if(data.files[key])setImage(new Image(),data.files[key],key);
initialized=true;publish();
