#!/usr/bin/env python3
"""Inventory enclosed transparency in an isolated SVG underlay render.

These are geometric candidates, not defect verdicts. Preserve real openings;
compare source and foreground-hidden views before changing the complete object.
Requires Pillow, numpy and OpenCV. Coordinates are input PNG pixels.
"""
import argparse, hashlib, json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageDraw

def inventory(alpha, threshold=250):
    transparent = (alpha < threshold).astype('uint8')
    count, labels, stats, centers = cv2.connectedComponentsWithStats(transparent, 8)
    h, w = alpha.shape
    rows = []
    for k in range(1, count):
        x,y,bw,bh,area = map(int,stats[k])
        if x == 0 or y == 0 or x+bw == w or y+bh == h:
            continue
        # Even a one-pixel enclosed component is retained.
        rows.append({'box_xyxy':[x,y,x+bw,y+bh], 'pixels':area,
                     'centroid':list(map(float,centers[k]))})
    rows.sort(key=lambda r:(r['box_xyxy'][1],r['box_xyxy'][0]))
    for i,r in enumerate(rows):
        r['id'] = f'hole_{i+1:03}'
    return rows

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--isolated',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--alpha-threshold',type=int,default=250)
    a=ap.parse_args()
    if not 1 <= a.alpha_threshold <= 255:
        ap.error('alpha-threshold must be 1..255')
    out=Path(a.out)
    out.mkdir(parents=True,exist_ok=False)
    src=Path(a.isolated).resolve()
    im=Image.open(src).convert('RGBA')
    rows=inventory(np.asarray(im)[:,:,3],a.alpha_threshold)
    bg=Image.new('RGBA',im.size,'#eeeeee');bg.alpha_composite(im)
    d=ImageDraw.Draw(bg)
    for r in rows:
        x,y,X,Y=r['box_xyxy'];d.rectangle((x,y,X-1,Y-1),outline='#c92a36',width=1)
        d.text((x,Y+1),r['id'],fill='#a31525')
    bg.convert('RGB').save(out/'numbered.png')
    data={'isolated':str(src),'sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
          'canvas':list(im.size),'coordinate_space':'input PNG pixels',
          'alpha_threshold':a.alpha_threshold,'holes':rows,
          'limits':'Enclosed transparency only. Edge-connected gaps and opaque white holes require separate review. No hole is automatically a defect; antialiasing and genuine openings are included.'}
    (out/'holes.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    print(json.dumps({'holes':len(rows),'out':str(out)}))

if __name__=='__main__':
    main()
