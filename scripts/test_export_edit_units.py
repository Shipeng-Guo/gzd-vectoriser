#!/usr/bin/env python3
"""Small native-XML export fixtures. Requires Pillow, Node/Playwright and a browser."""
import argparse,json,subprocess,os
from pathlib import Path
from PIL import Image
ap=argparse.ArgumentParser();ap.add_argument('--node',required=True);ap.add_argument('--browser',required=True);ap.add_argument('--out',type=Path,required=True);a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=False)
fixtures={
'plain':'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80"><defs><linearGradient id="g"><stop stop-color="red"/><stop offset="1" stop-color="blue"/></linearGradient><clipPath id="c"><rect x="0" y="0" width="16" height="12"/></clipPath></defs><g transform="translate(25 20)"><g id="unit" data-edit-unit="true" clip-path="url(#c)"><rect width="20" height="12" fill="url(#g)"/></g></g></svg>',
'prefixed':'<s:svg xmlns:s="http://www.w3.org/2000/svg" viewBox="0 0 100 80"><s:g id="unit" data-edit-unit="true" transform="translate(20 15)"><s:rect width="20" height="12" fill="#008000"/></s:g></s:svg>',
'nested':'<svg xmlns="http://www.w3.org/2000/svg" viewBox="10 20 100 100"><svg x="40" y="50" width="40" height="30" viewBox="0 0 20 15"><g transform="translate(2 3)"><g id="unit" data-edit-unit="true"><rect width="10" height="6" fill="#008000"/></g></g></svg></svg>'}
script=Path(__file__).with_name('export_edit_units.mjs');rows=[]
for name,xml in fixtures.items():
 f=a.out/(name+'.svg');f.write_text(xml);out=a.out/name
 proc=subprocess.run([a.node,str(script),str(f),'--out',str(out),'--browser',a.browser],capture_output=True,text=True)
 assert proc.returncode==0,(name,proc.stdout,proc.stderr)
 j=json.load(open(out/'index.json'));assert len(j['items'])==1
 im=Image.open(out/'unit.png').convert('RGBA');assert im.getpixel((0,0))[3]==0,(name,'nontransparent padding')
 if name in ('prefixed','nested'):assert im.getpixel((12,10))==(0,128,0,255),(name,im.getpixel((12,10)))
 if name=='nested':assert j['items'][0]['viewBox']==[38,50,32,24],j['items'][0]
 if name=='plain':
  assert im.getpixel((8,8))[3]==255;assert im.getpixel((25,8))[3]==0,'clip not preserved'
 rows.append({'fixture':name,'passed':True})
out=a.out/'trimmed';proc=subprocess.run([a.node,str(script),str(a.out/'plain.svg'),'--out',str(out),'--browser',a.browser,'--trim-transparent'],capture_output=True,text=True)
assert proc.returncode==0,(proc.stdout,proc.stderr)
j=json.load(open(out/'index.json'));box=j['items'][0]['viewBox'];assert 27<=box[2]<=29 and 23<=box[3]<=25,box
im=Image.open(out/'unit.png').convert('RGBA');assert im.getpixel((8,8))[3]==255 and im.getpixel((0,0))[3]==0
assert j['items'][0]['paintBoxInitialPixels'] is not None
rows.append({'fixture':'clip-painted-bounds-trim','passed':True})
ids=a.out/'bad-ids.json';ids.write_text('["missing"]');p=subprocess.run([a.node,str(script),str(a.out/'plain.svg'),'--out',str(a.out/'missing'),'--browser',a.browser,'--ids',str(ids)],capture_output=True,text=True);assert p.returncode!=0 and 'Missing/non-group' in p.stderr
rows.append({'fixture':'missing-unit-rejected','passed':True});(a.out/'results.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows))
