#!/usr/bin/env python3
"""Encode render_group_motion.mjs frames with a shared palette and decoded QA.
Requires Pillow. Output directory must be new. Source frames are unchanged.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
from PIL import Image, ImageOps, ImageSequence
from make_comparison_gif import quantize, WHITE, TEAL, BORDER, INK


def encode(manifest, out, width=None, frame_step=1):
    manifest, out = Path(manifest).resolve(), Path(out).resolve()
    if out.exists():
        raise ValueError('Output directory already exists.')
    m = json.loads(manifest.read_text())
    if not m.get('frames') or not m.get('source_unchanged'):
        raise ValueError('Completed, verified frame manifest required.')
    if not all(s.get('restored_pixels_equal') and s.get('watch_unchanged') and not s.get('clipped_at_peak') for s in m['scenes']):
        raise ValueError('Motion checks did not pass.')
    if not isinstance(frame_step,int) or not 1 <= frame_step <= 4:
        raise ValueError('frame-step must be an integer 1..4.')
    if frame_step > 1:
        retained=[]
        for i, f in enumerate(m['frames']):
            if f['position'] in (0,1) or i % frame_step == 0:
                retained.append(dict(f))
            else:
                retained[-1]['duration_ms'] += f['duration_ms']
        m['frames']=retained
    width = m['canvas'][0] if width is None else width
    if not isinstance(width, int) or width < 100 or width > 4096:
        raise ValueError('Width must be 100..4096.')
    size = (width, round(m['canvas'][1]*width/m['canvas'][0]))
    def read(f):
        p = (manifest.parent/f['file']).resolve()
        if not p.is_relative_to(manifest.parent):
            raise ValueError('Frame path escapes manifest directory.')
        with Image.open(p) as im:
            if list(im.size) != m['canvas']:
                raise ValueError('Inconsistent frame sizes.')
            rgb = im.convert('RGB')
        return rgb if rgb.size == size else rgb.resize(size, Image.Resampling.LANCZOS)
    indices = sorted(set([0, len(m['frames'])-1]+[i for i,f in enumerate(m['frames']) if f['position'] in (0,1)]))
    thumbs = [ImageOps.contain(read(m['frames'][i]), (400,400)) for i in indices]
    sample = Image.new('RGB', (400*4,400*((len(thumbs)+3)//4)), WHITE)
    for i,t in enumerate(thumbs): sample.paste(t,((i%4)*400,(i//4)*400))
    palette=sample.quantize(colors=252,method=Image.Quantize.MEDIANCUT)
    colors=palette.getpalette()[:756]; colors += [0]*(756-len(colors))
    palette.putpalette(colors+list(WHITE+TEAL+BORDER+INK))
    frames=[quantize(read(f),palette) for f in m['frames']]
    durations=[f['duration_ms'] for f in m['frames']]
    if any(not isinstance(n,int) or n<20 or n%10 for n in durations):
        raise ValueError('GIF duration must be integer multiples of 10ms, >=20ms.')
    out.mkdir(parents=True)
    gif=out/'exploded.gif'
    frames[0].save(gif,save_all=True,append_images=frames[1:],duration=durations,loop=0,disposal=1,optimize=False)
    # Compare every decoded frame against expected indexed pixels at that time.
    # Identical adjacent frames may have been merged by Pillow.
    expected_idx=0; remaining=durations[0]; elapsed=0; decoded=0
    from PIL import ImageChops
    with Image.open(gif) as g:
        if g.size!=size or g.info.get('loop')!=0: raise RuntimeError('GIF header failed.')
        for f in ImageSequence.Iterator(g):
            rgb=f.convert('RGB');duration=f.info['duration'];left=duration
            while left:
                if expected_idx>=len(frames) or ImageChops.difference(rgb,frames[expected_idx].convert('RGB')).getbbox():
                    raise RuntimeError('Decoded pixels differ from intended frame.')
                used=min(left,remaining);left-=used;remaining-=used
                if remaining==0:
                    expected_idx+=1
                    if expected_idx<len(durations):remaining=durations[expected_idx]
            elapsed+=duration;decoded+=1
        if elapsed!=sum(durations) or expected_idx!=len(frames): raise RuntimeError('GIF duration failed.')
    # Decoded contact sheet: original / displaced for each moving scene.
    targets=[];timestamp=0
    for f in m['frames']:
        if f['position'] in (0,1) and (f['scene'],f['position']) not in [(s,p) for _,s,p in targets]:
            targets.append((timestamp,f['scene'],f['position']))
        timestamp+=f['duration_ms']
    tw=400;th=round(size[1]*tw/size[0]);sheet=Image.new('RGB',(tw*2,th*len(m['scenes'])),WHITE)
    elapsed=0
    with Image.open(gif) as g:
        for f in ImageSequence.Iterator(g):
            dur=f.info['duration']
            for t,s,p in targets:
                if elapsed<=t<elapsed+dur:
                    sheet.paste(f.convert('RGB').resize((tw,th),Image.Resampling.LANCZOS),(int(p)*tw,s*th))
            elapsed+=dur
    sheet.save(out/'check.png')
    summary={'source_sha256':m['source_sha256'],'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'size':size,'duration_ms':elapsed,'frames':decoded,'bytes':gif.stat().st_size,'loop':0,'frame_step':frame_step,'decoded_pixels':'all frames matched','restoration':'artwork identical before/after each scene','scenes':[s['title'] for s in m['scenes']]}
    (out/'animation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    (out/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vector Components: Explode and Reassemble</title><style>body{max-width:1200px;margin:24px auto;padding:0 20px;font:17px/1.7 system-ui;color:#183d42}img{max-width:100%;height:auto}pre{white-space:pre-wrap}</style><h1>Vector Components: Explode and Reassemble</h1><p>Actual SVG groups move; local scenes temporarily hide unrelated layers. Each scene pauses in the exploded state to reveal the underlay, then returns to the exact original positions.</p><img src="exploded.gif" alt="SVG components moving apart, revealing the underlay, and returning to position"><p><a download href="exploded.gif">Download GIF</a> · '+str(size[0])+' × '+str(size[1])+' · '+str(elapsed/1000)+' second loop</p><pre><code>'+html.escape('<img src="exploded.gif" alt="Vector component disassembly demonstration" style="max-width:100%;height:auto;">')+'</code></pre></html>',encoding='utf-8')
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True,type=Path);p.add_argument('--out',required=True,type=Path);p.add_argument('--width',type=int);p.add_argument('--frame-step',type=int,default=1,help='Keep every Nth moving frame (1..4), preserving endpoints and total duration')
    a=p.parse_args()
    print(json.dumps(encode(**vars(a)),ensure_ascii=False))
