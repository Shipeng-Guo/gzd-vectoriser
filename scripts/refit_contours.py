#!/usr/bin/env python3
"""Conservative fitting of explicitly selected, source-traced closed SVG contours.

This is a geometric helper, NOT an image vectorizer. It does not reconstruct
occluded objects, join color partitions, or infer whether a corner is semantic.
Coordinates in each selected path must be in source-pixel units unless
--units-per-source-pixel is supplied. Unsupported path syntax is skipped.
Outputs never overwrite inputs; review the rendered result before acceptance.
"""
import argparse, collections, json, math, re, xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
import cv2
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import cKDTree
NS='http://www.w3.org/2000/svg'
ET.register_namespace('',NS)
TOKEN=re.compile(r'[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?')
SOURCE_METHODS={'local-source-contours-and-cubic-fit','source-traced'}


def bezier(c,t):
    t=np.asarray(t)[:,None]
    return (1-t)**3*c[0]+3*(1-t)**2*t*c[1]+3*(1-t)*t*t*c[2]+t**3*c[3]


def parse_closed(d,step=.6):
    """Sample M/L/H/V/C/Q/Z, absolute or relative. Reject open/mixed paths."""
    ts=TOKEN.findall(d); i=0; cmd=None; p=np.zeros(2); first=None; out=[]; pts=[]
    def numbers(n):
        nonlocal i
        if i+n>len(ts) or any(re.fullmatch('[A-Za-z]',v) for v in ts[i:i+n]): raise ValueError('invalid path arguments')
        a=np.array([float(v) for v in ts[i:i+n]]);i+=n;return a
    def line(q):
        nonlocal p,pts
        n=max(1,int(math.ceil(np.linalg.norm(q-p)/step)))
        pts.extend(p+(q-p)*k/n for k in range(1,n+1));p=q
    while i<len(ts):
        if re.fullmatch('[A-Za-z]',ts[i]): cmd=ts[i];i+=1
        if cmd is None: raise ValueError('missing command')
        lower=cmd.lower(); rel=cmd.islower()
        if lower=='m':
            if pts: raise ValueError('open subpath')
            q=numbers(2)+(p if rel else 0);p=q;first=q.copy();pts=[q.copy()];cmd='l' if rel else 'L'
        elif lower=='l': line(numbers(2)+(p if rel else 0))
        elif lower in ('h','v'):
            q=p.copy();v=numbers(1)[0];a=0 if lower=='h' else 1;q[a]=q[a]+v if rel else v;line(q)
        elif lower=='c':
            q=numbers(6).reshape(3,2)+(p if rel else 0);c=np.vstack([p,q]);n=max(2,int(math.ceil(np.linalg.norm(np.diff(c,axis=0),axis=1).sum()/step)));pts.extend(bezier(c,np.linspace(0,1,n+1)[1:]));p=q[-1]
        elif lower=='q':
            q=numbers(4).reshape(2,2)+(p if rel else 0);c=np.array([p,p+2/3*(q[0]-p),q[1]+2/3*(q[0]-q[1]),q[1]]);n=max(2,int(math.ceil(np.linalg.norm(np.diff(c,axis=0),axis=1).sum()/step)));pts.extend(bezier(c,np.linspace(0,1,n+1)[1:]));p=q[-1]
        elif lower=='z':
            if first is None: raise ValueError('close before move')
            line(first); a=np.asarray(pts)
            if np.linalg.norm(a[-1]-a[0])<1e-9: a=a[:-1]
            if len(a)<3: raise ValueError('degenerate closed path')
            out.append(a);pts=[];p=first;first=None;cmd=None
        else: raise ValueError('unsupported command '+cmd)
    if pts: raise ValueError('open path')
    if not out: raise ValueError('no closed subpaths')
    return out


def resample(a,step=.65):
    a=np.asarray(a); b=np.vstack([a,a[0]]); lengths=np.linalg.norm(np.diff(b,axis=0),axis=1);good=np.r_[True,lengths>1e-9];b=b[good]
    ds=np.r_[0,np.cumsum(np.linalg.norm(np.diff(b,axis=0),axis=1))]
    n=max(12,int(math.ceil(ds[-1]/step)));s=np.linspace(0,ds[-1],n,endpoint=False)
    return np.column_stack([np.interp(s,ds,b[:,j]) for j in range(2)]),ds[-1]/n


def area(p): return .5*np.sum(p[:,0]*np.roll(p[:,1],-1)-p[:,1]*np.roll(p[:,0],-1))
def unit(v): return v/max(1e-12,np.linalg.norm(v))


def smooth_points(p,step,sigma,corner_degrees=65):
    """Suppress pixel-scale curvature; protect salient corners and narrow necks."""
    n=len(p); sm=gaussian_filter1d(p,sigma/step,axis=0,mode='wrap')
    w=max(2,min(n//10,round(4*sigma/step)))
    a=p-np.roll(p,w,axis=0);b=np.roll(p,-w,axis=0)-p
    cosine=np.sum(a*b,axis=1)/(np.maximum(1e-9,np.linalg.norm(a,axis=1)*np.linalg.norm(b,axis=1)))
    angles=np.degrees(np.arccos(np.clip(cosine,-1,1)))
    candidates=np.where(angles>corner_degrees)[0]; corners=[]
    for j in candidates[np.argsort(angles[candidates])[::-1]]:
        if all(min(abs(j-k),n-abs(j-k))>w for k in corners): corners.append(int(j))
    weights=np.ones(n)
    for j in corners:
        d=np.minimum(np.abs(np.arange(n)-j),n-np.abs(np.arange(n)-j))
        weights=np.minimum(weights,np.minimum(1,(d/max(1,w))**2))
    # Opposite sides of a thin neck are distant along the contour, close in XY.
    # Constrain their smoothing displacement; topology is checked again below.
    tree=cKDTree(p); max_shift=np.full(n,np.inf); narrow=0
    for j,near in enumerate(tree.query_ball_point(p,4*sigma)):
        k=np.asarray(near,dtype=int);distance=np.minimum(abs(k-j),n-abs(k-j));k=k[distance>max(6,round(8*sigma/step))]
        if len(k):
            width=np.min(np.linalg.norm(p[k]-p[j],axis=1));max_shift[j]=max(.08,.1*width);narrow+=1
    delta=(sm-p)*weights[:,None];mag=np.linalg.norm(delta,axis=1);delta*=np.minimum(1,max_shift/np.maximum(1e-9,mag))[:,None]
    return p+delta,sorted(corners),narrow


def fit_piece(p,tolerance,tangent0=None,tangent1=None):
    """Recursive least-squares cubic fit, error measured at sample parameters."""
    if len(p)<3:
        d=(p[-1]-p[0])/3;return [np.array([p[0],p[0]+d,p[-1]-d,p[-1]])]
    s=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))];t=s/max(s[-1],1e-9)
    tangent0=unit(p[min(3,len(p)-1)]-p[0]) if tangent0 is None else tangent0
    tangent1=unit(p[-1]-p[max(0,len(p)-4)]) if tangent1 is None else tangent1
    b0=(1-t)**3;b1=3*t*(1-t)**2;b2=3*t*t*(1-t);b3=t**3
    A=np.stack([b1[:,None]*tangent0,-b2[:,None]*tangent1],axis=2).reshape(-1,2)
    rhs=(p-(b0+b1)[:,None]*p[0]-(b2+b3)[:,None]*p[-1]).reshape(-1)
    alpha=np.linalg.lstsq(A,rhs,rcond=None)[0];chord=np.linalg.norm(p[-1]-p[0]);alpha=np.clip(alpha,.01,max(chord*1.5,.1))
    c=np.array([p[0],p[0]+alpha[0]*tangent0,p[-1]-alpha[1]*tangent1,p[-1]])
    error=np.linalg.norm(bezier(c,t)-p,axis=1);idx=int(np.argmax(error))
    if error[idx]<=tolerance or len(p)<=4: return [c]
    idx=max(2,min(len(p)-3,idx));middle=unit(p[idx+1]-p[idx-1])
    return fit_piece(p[:idx+1],tolerance,tangent0,middle)+fit_piece(p[idx:],tolerance,middle,tangent1)


def fit_closed(p,corners,tolerance):
    n=len(p)
    anchors=sorted(set(corners)) if len(corners)>=2 else list(range(0,n,max(1,n//4)))
    # Long arcs split adaptively by fitting; prominent corners remain endpoints.
    curves=[]
    for j,a in enumerate(anchors):
        b=anchors[(j+1)%len(anchors)];indices=np.arange(a,(b if b>a else b+n)+1)%n
        t0=None if a in corners else unit(p[(a+1)%n]-p[(a-1)%n])
        t1=None if b in corners else unit(p[(b+1)%n]-p[(b-1)%n])
        curves+=fit_piece(p[indices],tolerance,t0,t1)
    return curves


def topology(subs,scale=2):
    pts=np.concatenate(subs);lo=np.floor(pts.min(axis=0))-3;hi=np.ceil(pts.max(axis=0))+3
    if np.max(hi-lo)*scale>1800: scale=1800/np.max(hi-lo)
    wh=np.ceil((hi-lo)*scale).astype(int)+1;mask=np.zeros((wh[1],wh[0]),np.uint8)
    cv2.fillPoly(mask,[np.round((p-lo)*scale).astype(np.int32) for p in subs],255)
    contours,h=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    # Tiny sampling islands are ignored, but holes of >= 1 source pixel remain.
    if h is None:return 0,0
    significant=[i for i,c in enumerate(contours) if cv2.contourArea(c)>=scale*scale]
    return sum(h[0,i,3]<0 for i in significant),sum(h[0,i,3]>=0 for i in significant)


def fmt(curves):
    f=lambda x:format(float(x),'.3f').rstrip('0').rstrip('.')
    result='M'+','.join(map(f,curves[0][0]))
    for c in curves:result+='C'+' '.join(','.join(map(f,p)) for p in c[1:])
    return result+'Z'


def refit_path(d,sigma=1.8,tolerance=.65,min_area=35,min_span=5,max_displacement=3.5):
    chunks=re.findall(r'[Mm][^Mm]*',d)
    if len(chunks)>1 and any(c.startswith('m') for c in chunks[1:]):raise ValueError('Relative compound moves require normalization before fitting')
    subs=parse_closed(d);metrics={'subpaths':len(subs),'old_commands':len(re.findall('[CcLl]',d)),'new_commands':0,'protected_corners':0,'narrow_samples':0}
    revised=[];outputs=[];any_changed=False
    for raw,chunk in zip(subs,chunks):
        if abs(area(raw))<min_area or min(np.ptp(raw,axis=0))<min_span:
            revised.append(raw);outputs.append(chunk);continue
        p,step=resample(raw);smooth,corners,narrow=smooth_points(p,step,sigma)
        curves=fit_closed(smooth,corners,tolerance);q=np.vstack([bezier(c,np.linspace(0,1,max(8,int(np.linalg.norm(np.diff(c,axis=0),axis=1).sum()*2))))[:-1] for c in curves])
        if area(p)*area(q)<=0:return d,dict(metrics,status='rejected_orientation')
        if abs(abs(area(q))/max(abs(area(p)),1)-1)>.045:return d,dict(metrics,status='rejected_area')
        dist=max(cKDTree(q).query(p)[0].max(),cKDTree(p).query(q)[0].max())
        if dist>max_displacement:return d,dict(metrics,status='rejected_displacement',displacement=float(dist))
        revised.append(q);outputs.append(fmt(curves));any_changed=True;metrics['new_commands']+=len(curves);metrics['protected_corners']+=len(corners);metrics['narrow_samples']+=narrow
    if not any_changed:return d,dict(metrics,status='skipped_small_or_thin')
    if topology(subs)!=topology(revised):return d,dict(metrics,status='rejected_topology')
    new=' '.join(outputs)
    return new,dict(metrics,status='changed',max_sigma=sigma,tolerance=tolerance)


def apply_svg(source,output,groups,*,sigma=1.8,tolerance=.65,units_per_source_pixel=1,min_area=35,min_span=5,max_displacement=3.5):
    source,output=Path(source),Path(output)
    if source.resolve()==output.resolve() or output.exists():raise ValueError('Output must be a new file, never the input or an existing file')
    tree=ET.parse(source);root=tree.getroot();ids={e.get('id'):e for e in root.iter() if e.get('id')}
    missing=set(groups)-set(ids)
    if missing:raise ValueError('Unknown exact group IDs: '+', '.join(sorted(missing)))
    for key in groups:
        e=ids[key]
        if e.tag!='{'+NS+'}g':raise ValueError('Selection must be an exact SVG group ID: '+key)
        if e.get('data-method') not in SOURCE_METHODS:raise ValueError('Selection is not explicitly source-traced: '+key)
    selected=set();report={'source':str(source),'output':str(output),'groups':{},'parameters':{'sigma_source_px':sigma,'fit_error_source_px':tolerance,'units_per_source_pixel':units_per_source_pixel}}
    for key in groups:
        e=ids[key];stats=collections.Counter();records=[]
        details=ids.get(key+'.details',e)
        for p in details.iter('{'+NS+'}path'):
            if id(p) in selected:continue
            selected.add(id(p))
            # Only old detail trace groups are eligible. Underlays added by hand
            # and individually reconstructed boundaries stay unchanged.
            if ((p.get('id') and not re.fullmatch(re.escape(key)+r'\.p\d+',p.get('id'))) and p.get('data-refit')!='true') or p.get('data-inference') or p.get('data-manual'):
                stats['skipped_named_or_manual']+=1;continue
            try:
                d,m=refit_path(p.get('d',''),sigma=sigma*units_per_source_pixel,tolerance=tolerance*units_per_source_pixel,min_area=min_area*units_per_source_pixel**2,min_span=min_span*units_per_source_pixel,max_displacement=max_displacement*units_per_source_pixel)
                if m['status']=='changed':p.set('d',d)
                stats[m['status']]+=1;stats['input_commands']+=m.get('old_commands',0);stats['output_commands']+=len(re.findall('[CcLl]',d));records.append(m)
            except (ValueError,RecursionError) as exc:stats['skipped_unsupported']+=1;records.append({'status':'skipped_unsupported','reason':str(exc)})
        report['groups'][key]={'counts':dict(stats),'paths':records}
    output.parent.mkdir(parents=True,exist_ok=True);tree.write(output,encoding='utf-8',xml_declaration=True)
    return report


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('input');ap.add_argument('output');ap.add_argument('--groups',nargs='+',required=True,help='Exact group IDs, no wildcards; data-method must be source-traced or local-source-contours-and-cubic-fit. Named paths require data-refit=true unless named GROUP.pN. Manual/inferred paths always skip.')
    ap.add_argument('--sigma',type=float,default=1.8,help='Source-pixel smoothing length');ap.add_argument('--tolerance',type=float,default=.65,help='Source-pixel cubic fitting error');ap.add_argument('--units-per-source-pixel',type=float,default=1);ap.add_argument('--min-area',type=float,default=35);ap.add_argument('--min-span',type=float,default=5);ap.add_argument('--max-displacement',type=float,default=3.5);ap.add_argument('--report',required=True)
    a=ap.parse_args()
    if not all(math.isfinite(v) and v>0 for v in (a.sigma,a.tolerance,a.units_per_source_pixel,a.min_area,a.min_span,a.max_displacement)):ap.error('All geometric parameters must be positive')
    report=apply_svg(a.input,a.output,a.groups,sigma=a.sigma,tolerance=a.tolerance,units_per_source_pixel=a.units_per_source_pixel,min_area=a.min_area,min_span=a.min_span,max_displacement=a.max_displacement)
    Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v['counts'] for k,v in report['groups'].items()},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
