#!/usr/bin/env python3
"""Behavioral regression for the bounded SVG/native-PPTX bridge; writes only into a new test directory."""
import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as E
import zipfile

SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="100 50 400 225" font-family="Arial">
<defs><linearGradient id="wash" x1="0%" y1="0%" x2="0%" y2="100%">
<stop offset="0%" stop-color="#ffeecc"/><stop offset="100%" stop-color="#ee9955"/>
</linearGradient></defs>
<rect id="background" x="100" y="50" width="400" height="225" fill="#ffffff"/>
<g id="component" transform="translate(150 100)" data-edit-unit="true">
 <rect id="base" x="0" y="0" width="100" height="65" rx="10" fill="#d8e8ff" stroke="#335588" stroke-width="2"/>
 <g id="rotated" transform="translate(25 20) rotate(30)">
  <path id="curve" d="M 0 0 C 8 -4 24 12 40 0" fill="none" stroke="#224466" stroke-width="3" stroke-linecap="round"/>
  <text id="rotated-label" x="15" y="24" font-size="12" font-weight="bold" fill="#224466">Edit A</text>
 </g>
</g>
<g id="independent" transform="translate(300 110)">
 <circle id="disk" cx="30" cy="25" r="20" fill="#dd6688"/>
 <text id="regular-label" x="0" y="70" font-size="16" fill="#221133">Regular</text>
 <text id="italic-label" x="0" y="95" font-size="16" font-style="italic" fill="#221133">Italic</text>
</g>
<rect id="gradient" x="405" y="90" width="60" height="95" rx="12" ry="7" fill="url(#wash)"/>
</svg>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', required=True)
    parser.add_argument('--browser', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = out / 'fixture.svg'
    source.write_text(SVG)
    bridge = Path(__file__).with_name('svg_to_pptx.mjs')
    def run(file, dest):
        return subprocess.run([args.node, str(bridge), str(file), '--out', str(dest),
                               '--browser', args.browser, '--python', sys.executable,
                               '--width', '800'], capture_output=True, text=True)
    result = run(source, out / 'valid')
    if result.returncode:
        raise RuntimeError(result.stderr or result.stdout)
    scene = json.loads((out / 'valid/scene.json').read_text())
    items = {i['id']: i for i in scene['items']}
    assert scene['canvas'] == [800, 450]
    assert len(items) == 8 and items['curve']['groups'] == ['component', 'rotated']
    # Nonzero viewBox, ancestor translation and rotation compose once.
    assert abs(items['base']['x'] - 100) < 1e-6
    assert abs(items['base']['y'] - 100) < 1e-6
    curve = items['curve']
    start = curve['commands'][0]['moveTo']
    assert abs(curve['x'] + start['x'] - 150) < 1e-6
    assert abs(curve['y'] + start['y'] - 140) < 1e-6
    control = curve['commands'][1]['cubicBezTo']
    assert abs(curve['x'] + control['x1'] - (150 + 2*(8*math.cos(math.pi/6)+4*math.sin(math.pi/6)))) < 1e-6
    assert items['rotated-label']['bold'] is True
    assert items['regular-label']['bold'] is False
    assert items['italic-label']['italic'] is True
    assert abs(items['rotated-label']['rotation'] - 30) < 1e-6
    assert items['gradient']['fill']['stops'][-1]['offset'] == 100000
    ns = {'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
          'a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
    with zipfile.ZipFile(out/'valid/candidate.pptx') as z:
        root = E.fromstring(z.read('ppt/slides/slide1.xml'))
        assert not root.findall('.//p:pic', ns)
        shapes = root.findall('.//p:sp', ns)
        assert len(shapes) == 8
        names = [s.find('p:nvSpPr/p:cNvPr', ns).get('name') for s in shapes]
        assert names == list(items), 'Z-order changed'
        assert len(root.findall('.//a:t', ns)) == 3
        assert len(root.findall('.//p:grpSp', ns)) == 3
        ids = [n.get('id') for n in root.findall('.//p:cNvPr', ns)]
        assert len(ids) == len(set(ids))
        for g in root.findall('.//p:grpSp', ns):
            xf = g.find('p:grpSpPr/a:xfrm', ns)
            assert xf.find('a:off', ns).attrib == xf.find('a:chOff', ns).attrib
            assert xf.find('a:ext', ns).attrib == xf.find('a:chExt', ns).attrib
        assert all(l.get('noGrp') != '1' for l in root.findall('.//a:spLocks', ns))
        assert any(s.find('p:txBody', ns) is not None for s in shapes)
        assert root.findall('.//a:cubicBezTo', ns), 'Curves were flattened into an image'

    # These must be rejected, not silently removed or flattened.
    invalid = {
      'relative-path': SVG.replace('M 0 0 C 8 -4 24 12 40 0', 'm 0 0 c 8 -4 24 12 40 0'),
      'opacity': SVG.replace('id="disk"', 'id="disk" opacity="0.5"'),
      'skew': SVG.replace('rotate(30)', 'skewX(20)'),
      'mask': SVG.replace('id="base"', 'id="base" mask="url(#unknown)"'),
      'rich-text': SVG.replace('>Regular</text>', '><tspan>Regular</tspan></text>'),
      'image': SVG.replace('</svg>', '<image id="bitmap" href="sample.png"/></svg>'),
      'duplicate-id': SVG.replace('id="disk"', 'id="base"'),
    }
    for name, xml in invalid.items():
        file = out/(name+'.svg'); file.write_text(xml)
        dest = out/name
        r = run(file, dest)
        assert r.returncode != 0, name+' unexpectedly succeeded'
        assert not (dest/'candidate.pptx').exists(), name+' emitted a false native candidate'
    summary = {'pass':True,'native_shapes':8,'native_text':3,'native_groups':3,
               'rejection_cases':list(invalid),'visual_review_required':True}
    (out/'result.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))

if __name__ == '__main__':
    main()
