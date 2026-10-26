#!/usr/bin/env python3
"""Anonymous SVG behavior tests for movement, isolation, restoration and GIF encoding."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from PIL import Image
from encode_motion_gif import encode

p=argparse.ArgumentParser();p.add_argument('--node',default='node');p.add_argument('--browser',required=True);a=p.parse_args()
script=Path(__file__).with_name('render_group_motion.mjs')
with tempfile.TemporaryDirectory() as temp:
    root=Path(temp); svg=root/'input.svg'
    svg.write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240" viewBox="0 0 400 240"><rect id="base" x="10" y="10" width="380" height="220" fill="#faead0"/><g id="parent" transform="translate(90 95) rotate(25) scale(1.2)"><g id="unit" transform="rotate(-10)"><rect id="body" x="-12" y="-10" width="24" height="20" fill="#3498ad"/><text id="label" y="30" font-size="12">A</text></g></g><g id="units"><g id="one"><circle cx="200" cy="90" r="12" fill="#aa0066"/></g><g id="two"><circle cx="270" cy="140" r="12" fill="#005577"/></g></g></svg>''')
    base=svg.read_bytes()
    cfg={'canvas':[600,420],'fps':10,'scenes':[{'title':'Nested transform','viewBox':[0,0,400,240],'moves':[{'id':'unit','delta':[30,15]}],'watch':['base'],'retain':['base','unit'],'travel_seconds':.2,'hold_seconds':.1,'rest_seconds':.1},{'title':'Radial units','viewBox':[0,0,400,240],'moves':[{'childrenOf':'units','radial':{'center':[230,115],'distance':20}}],'watch':['base'],'travel_seconds':.2,'hold_seconds':.1,'rest_seconds':.1}]}
    def run(c,name,expected=0):
        path=root/(name+'.json');path.write_text(json.dumps(c));out=root/name
        r=subprocess.run([a.node,str(script),'--svg',str(svg),'--config',str(path),'--out',str(out),'--browser',a.browser],capture_output=True,text=True)
        assert (r.returncode==0)==(expected==0),r.stdout+r.stderr
        return out,r
    out,_=run(cfg,'good');m=json.loads((out/'frames.json').read_text())
    assert all(s['restored_pixels_equal'] and s['watch_unchanged'] and s['max_screen_delta_error']<.05 for s in m['scenes'])
    assert m['scenes'][0]['peak']['moved'][0]['members']==['body','label']
    assert svg.read_bytes()==base
    summary=encode(out/'frames.json',root/'gif',width=400)
    assert summary['decoded_pixels']=='all frames matched'
    compact=encode(out/'frames.json',root/'compact',width=400,frame_step=2)
    assert compact['duration_ms']==summary['duration_ms'] and compact['frames']<summary['frames']
    with Image.open(root/'gif'/'exploded.gif') as im: assert im.convert('RGB').getpixel((0,100))==(255,255,255)
    print('PASS: nested transforms use root coordinates; labels travel; watched base fixed; pixels return; shared-palette GIF decodes exactly.')
    bad=json.loads(json.dumps(cfg));bad['scenes'][0]['moves'].append({'id':'parent','delta':[1,1]})
    _,r=run(bad,'overlap',1);assert 'Overlapping or duplicate moved units' in r.stderr
    print('PASS: ancestor/descendant simultaneous movement rejected.')
    bad=json.loads(json.dumps(cfg));bad['scenes'][0]['moves'][0]['delta']=[1000,0]
    _,r=run(bad,'clipping',1);assert 'Motion verification failed' in r.stderr and 'unit' in r.stderr
    print('PASS: off-canvas movement rejected.')
