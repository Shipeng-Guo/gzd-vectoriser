#!/usr/bin/env python3
"""Domain-independent visual discrepancy proposals, never semantic approval.
Requires Pillow, numpy, opencv-python. Inputs must already share coordinates.
Outputs separate channels, native-resolution coverage, crop evidence and an HTML wipe viewer.
"""
import argparse,json,hashlib,math,html,shutil,time,uuid
from pathlib import Path
import numpy as np,cv2
from PIL import Image,ImageDraw
from exact_difference import export as export_exact, normalize, white
CHANNELS={'fine_color':'Fine colour / local detail','missing_edges':'Source-only edges','added_edges':'Candidate-only edges','ink_weight':'Dark line / glyph weight','broad_tone':'Broad shading / colour','added_brightness':'Added bright area / background','fill_gaps':'Unexpected white in coloured source regions'}
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rgb(p):
 return white(normalize(p)[0])
def compute_maps(a,b,tolerance=1.5):
 if a.shape!=b.shape:raise ValueError('Input canvases differ; no implicit resize or local warp is allowed.')
 af,bf=a.astype(np.float32),b.astype(np.float32);ga=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY);gb=cv2.cvtColor(b,cv2.COLOR_RGB2GRAY)
 blur=lambda x,s:cv2.GaussianBlur(x,(0,0),s)
 ea,eb=cv2.Canny(ga,55,130),cv2.Canny(gb,55,130)
 da=cv2.distanceTransform((ea==0).astype('uint8'),cv2.DIST_L2,3);db=cv2.distanceTransform((eb==0).astype('uint8'),cv2.DIST_L2,3)
 chroma_a=np.max(af,axis=2)-np.min(af,axis=2);chroma_b=np.max(bf,axis=2)-np.min(bf,axis=2)
 ink=(((ga<185)&(chroma_a<55))|((gb<185)&(chroma_b<55))).astype('uint8');ink=cv2.dilate(ink,np.ones((5,5),np.uint8))
 sigma=max(3,min(18,a.shape[1]*.004));fine=np.max(abs(blur(af,.65)-blur(bf,.65)),axis=2)
 return {'fine_color':fine,'missing_edges':blur(((ea>0)&(db>tolerance)).astype('float32'),1.2)*255,'added_edges':blur(((eb>0)&(da>tolerance)).astype('float32'),1.2)*255,'ink_weight':abs(blur(ga.astype('float32'),.6)-blur(gb.astype('float32'),.6))*ink,'broad_tone':np.max(abs(blur(af,sigma)-blur(bf,sigma)),axis=2),'added_brightness':blur(np.maximum(gb.astype('float32')-ga.astype('float32'),0)*((gb>215)&(ga<240)),1.2),'fill_gaps':blur(np.maximum(gb.astype('float32')-ga.astype('float32'),0)*((gb>225)&(chroma_b<20)&(chroma_a>24)&(ga<228)),.8)}
def propose(m,name,budget):
 h,w=m.shape;integral=cv2.integral(m);res=[]
 sizes=[max(32,round(w*f)) for f in ([.05,.12,.22] if name=='broad_tone' else [.025,.055,.12])]
 for size in sizes:
  for y in sorted(set(list(range(0,max(1,h-size),max(16,size//2)))+[max(0,h-size)])):
   for x in sorted(set(list(range(0,max(1,w-size),max(16,size//2)))+[max(0,w-size)])):
    x1,y1=min(w,x+size),min(h,y+size);score=(integral[y1,x1]-integral[y,x1]-integral[y1,x]+integral[y,x])/((x1-x)*(y1-y))
    if score>1.0:res.append((float(score),[x,y,x1,y1]))
 selected=[]
 for score,box in sorted(res,reverse=True):
  cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
  if any(abs(cx-(p['box_xyxy'][0]+p['box_xyxy'][2])/2)<.6*min(box[2]-box[0],p['box_xyxy'][2]-p['box_xyxy'][0]) and abs(cy-(p['box_xyxy'][1]+p['box_xyxy'][3])/2)<.6*min(box[3]-box[1],p['box_xyxy'][3]-p['box_xyxy'][1]) for p in selected):continue
  selected.append({'id':f'{name}_{len(selected)+1:02d}','channel':name,'box_xyxy':box,'signal':round(score,4),'status':'needs_review'})
  if len(selected)>=budget:break
 return selected

def validate_requirements(requirements):
 if not isinstance(requirements,dict) or any(not isinstance(k,str) or not k.strip() or not isinstance(v,str) or not v.strip() for k,v in requirements.items()):
  raise ValueError('requirements must be an object of named, nonempty source expectations')

def save_evidence(a,b,item,out,lean=False):
 x0,y0,x1,y1=item['box_xyxy'];aa=a[y0:y1,x0:x1];bb=b[y0:y1,x0:x1];d=out/item['id'];d.mkdir(parents=True,exist_ok=True)
 if not lean:
  for name,im in [('source',aa),('candidate',bb),('overlay',((aa.astype(float)+bb)/2).astype('uint8'))]:Image.fromarray(im).save(d/(name+'.png'))
 # Never downscale the evidence: small line widths remain visible. Large cards may be opened at native size.
 h,w=aa.shape[:2];card=Image.new('RGB',(2*w,h+25),'#ecf3f0');card.paste(Image.fromarray(aa),(0,25));card.paste(Image.fromarray(bb),(w,25));draw=ImageDraw.Draw(card);draw.text((5,6),'SOURCE',fill='black');draw.text((w+5,6),'CANDIDATE',fill='black');card.save(d/'pair.png')
 if not lean:
  for pc in [25,50,75]:
   cut=round(w*pc/100);v=bb.copy();v[:,:cut]=aa[:,:cut];Image.fromarray(v).save(d/f'wipe_{pc}.png')
 item['source_crop_sha256']=hashlib.sha256(aa.tobytes()).hexdigest();item['candidate_crop_sha256']=hashlib.sha256(bb.tobytes()).hexdigest();item['evidence']=str((d/'pair.png').resolve());item['scan_evidence_sha256']=digest(d/'pair.png')
def main():
 started_at_ns=time.time_ns()
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--reference',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True);ap.add_argument('--out',type=Path,required=True);ap.add_argument('--per-channel',type=int,default=6);ap.add_argument('--tile-size',type=int,default=760);ap.add_argument('--tolerance-px',type=float,default=1.5);ap.add_argument('--regions',type=Path);ap.add_argument('--exact-tile-size',type=int,default=96);ap.add_argument('--previous-exact',type=Path,help='Prior exact/manifest.json for pixel transitions');ap.add_argument('--lean',action='store_true',help='Write scan.json and native pair evidence only; detection and review scope are unchanged.');args=ap.parse_args()
 if args.per_channel<1 or args.tile_size<64 or args.tolerance_px<0 or args.exact_tile_size<8:ap.error('invalid parameters')
 ar,br=normalize(args.reference)[0],normalize(args.candidate)[0];a,b=white(ar),white(br)
 try:maps=compute_maps(a,b,args.tolerance_px)
 except ValueError as e:ap.error(str(e))
 out=args.out;out.mkdir(parents=True,exist_ok=True);h,w=a.shape[:2];items=[];stats={};components=[]
 for name,m in maps.items():
  proposed=propose(m,name,args.per_channel);items+=proposed;stats[name]={'mean':float(m.mean()),'max':float(m.max()),'proposals':len(proposed)}
  # Keep the complete thresholded component inventory, independently of top-window budgets.
  threshold=6 if name=='broad_tone' else 16
  binary=(m>threshold).astype('uint8');binary=cv2.morphologyEx(binary,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
  n,labels,ss,cent=cv2.connectedComponentsWithStats(binary,8);component_count=0
  for k in range(1,n):
   x,y,cw,ch,area=map(int,ss[k])
   if area<4:continue
   components.append({'id':f'{name}_component_{k:05d}','channel':name,'box_xyxy':[max(0,x-6),max(0,y-6),min(w,x+cw+6),min(h,y+ch+6)],'area_pixels':area,'threshold':threshold,'status':'needs_review'});component_count+=1
  stats[name]['components']=component_count
  # Native map retained so small changes are not lost in the thumbnail.
  if not args.lean:
   Image.fromarray(np.clip(m,0,255).astype('uint8')).save(out/(name+'_native.png'))
   heat=cv2.applyColorMap(np.clip(m/65*255,0,255).astype('uint8'),cv2.COLORMAP_TURBO)[:,:,::-1];im=Image.fromarray((.4*a+.6*heat).astype('uint8'));im.thumbnail((1600,1600));im.save(out/(name+'.png'))
 coverage=[]
 for y in range(0,h,args.tile_size):
  for x in range(0,w,args.tile_size):coverage.append({'id':f'coverage_{len(coverage)+1:02d}','channel':'coverage','box_xyxy':[x,y,min(w,x+args.tile_size),min(h,y+args.tile_size)],'status':'needs_review'})
 exact=export_exact(args.reference,args.candidate,out/'exact',args.exact_tile_size,args.previous_exact)
 exact_regions=[dict(t) for t in exact['tiles']]
 seeds=[]
 if args.regions:
  raw=json.loads(args.regions.read_text());assert raw['canvas']==[w,h],'region canvas differs'
  for item in raw['regions']:
   box=item['box_xyxy'];assert len(box)==4 and 0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h,'invalid region'
   if 'requirements' in item:
    try:validate_requirements(item['requirements'])
    except ValueError as e:ap.error(str(e))
   seeds.append(dict(item,channel='source_review',status='needs_review'))
 allitems=items+coverage+seeds+exact_regions;ids=[i['id'] for i in allitems]
 if len(ids)!=len(set(ids)):ap.error('duplicate region IDs')
 for item in allitems:
  x0,y0,x1,y1=item['box_xyxy'];item['channel_signals']={k:round(float(v[y0:y1,x0:x1].mean()),4) for k,v in maps.items()};save_evidence(a,b,item,out,args.lean)
  # Bind normalized RGBA, including differences hidden by white compositing.
  item['source_crop_sha256']=hashlib.sha256(ar[y0:y1,x0:x1].tobytes()).hexdigest()
  item['candidate_crop_sha256']=hashlib.sha256(br[y0:y1,x0:x1].tobytes()).hexdigest()
  item['crop_hash_format']='normalized_uint8_rgba'
 result={'version':4,'run_id':str(uuid.uuid4()),'started_at_ns':started_at_ns,'canvas':[w,h],'reference_sha256':digest(args.reference),'candidate_sha256':digest(args.candidate),'reference':str(args.reference.resolve()),'candidate':str(args.candidate.resolve()),'parameters':{'per_channel':args.per_channel,'tile_size':args.tile_size,'tolerance_px':args.tolerance_px},'limits':'Proposals are not error labels or an exhaustive semantic audit. No local warp. Review source-defined critical regions plus appearance, labels, terminals, line weight, backgrounds and tone. Authorized asset policies belong in the review ledger; no pixel threshold grants approval.','channels':stats,'components':components,'proposals':items,'coverage':coverage,'source_regions':seeds}
 result['exact']={'manifest':str((out/'exact/manifest.json').resolve()),'manifest_sha256':digest(out/'exact/manifest.json'),'proof':exact['proof']}
 result['exhaustive_regions']=exact_regions
 result['output_mode']='lean' if args.lean else 'full'
 (out/'scan.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
 if args.lean:
  print(json.dumps({'output_mode':'lean','proposals':len(items),'coverage':len(coverage),'source_regions':len(seeds),'channels':stats},ensure_ascii=False));return
 # A generic viewer makes every candidate and every coverage cell inspectable with a wipe.
 cards=''.join('<button onclick="pick('+str(i)+')">'+html.escape(it['id'])+'</button>' for i,it in enumerate(allitems));data=json.dumps(allitems,ensure_ascii=False).replace('</',r'<\/')
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Visual difference review</title><style>body{font:16px system-ui;background:#eef4f1;color:#17383e;margin:24px}button{padding:8px;margin:4px;border:1px solid #abc;background:white;border-radius:6px;cursor:pointer}.view{position:relative;max-width:1100px;background:white}.view img{width:100%;display:block}.over{position:absolute;inset:0;clip-path:inset(0 50% 0 0)}input{width:min(100%,1100px)}.thumb{width:min(100%,760px)}nav{max-height:180px;overflow:auto}h1{font-size:26px}</style><h1>Separate channels · fixed coordinates</h1><p><a href="exact/index.html">Complete pixel inventory / all difference IDs</a></p><p>Candidate regions require judgment. Source left / candidate right. Review permitted differences separately.</p><nav>CARDS</nav><h2 id="title"></h2><div class="view"><img id="b"><img id="a" class="over"></div><input aria-label="Source coverage" type="range" min="0" max="100" value="50" oninput="document.getElementById('a').style.clipPath='inset(0 '+(100-this.value)+'% 0 0)'"><p><a id="pair">Native-resolution side by side</a> · <a id="overlay">Overlay</a></p><script>const data=DATA;function pick(i){const d=data[i];document.getElementById('title').textContent=d.id+' / '+d.channel;document.getElementById('a').src=d.id+'/source.png';document.getElementById('b').src=d.id+'/candidate.png';document.getElementById('pair').href=d.id+'/pair.png';document.getElementById('overlay').href=d.id+'/overlay.png'}pick(0)</script></html>'''.replace('CARDS',cards).replace('DATA',data)
 (out/'index.html').write_text(page);print(json.dumps({'proposals':len(items),'coverage':len(coverage),'source_regions':len(seeds),'channels':stats},ensure_ascii=False))
if __name__=='__main__':main()
