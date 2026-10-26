#!/usr/bin/env python3
"""Restore SVG hierarchy on a single-slide Artifact Tool draft without moving its leaves."""
import argparse
import json
import math
from pathlib import Path
import xml.etree.ElementTree as E
import zipfile

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS = {'p': P, 'a': A}
E.register_namespace('p', P)
E.register_namespace('a', A)


def convert(scene, source, output):
    with zipfile.ZipFile(source) as z:
        files = {n: z.read(n) for n in z.namelist()}
    slides = [n for n in files if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
    if slides != ['ppt/slides/slide1.xml']:
        raise ValueError('This bridge requires exactly one slide.')
    root = E.fromstring(files[slides[0]])
    tree = root.find('.//p:spTree', NS)
    leaves = tree.findall('p:sp', NS)
    shapes = {s.find('p:nvSpPr/p:cNvPr', NS).get('name'): s for s in leaves}
    items = scene['items']
    if len(shapes) != len(leaves) or set(shapes) != {i['id'] for i in items}:
        raise ValueError('Draft shape names do not match scene IDs one-to-one.')
    if tree.findall('p:grpSp', NS) or tree.findall('p:pic', NS):
        raise ValueError('Draft already contains groups or images.')
    next_id = max(int(n.get('id')) for n in root.findall('.//p:cNvPr', NS)) + 1

    for it in items:
        s = shapes[it['id']]
        for lock in s.findall('.//a:spLocks', NS):
            lock.attrib.pop('noGrp', None)
        for ln in s.findall('p:spPr/a:ln', NS):
            ln.set('cap', {'round': 'rnd', 'square': 'sq', 'butt': 'flat'}[it['lineCap']])
            for child in list(ln):
                if child.tag.split('}')[-1] in ['miter', 'round', 'bevel']:
                    ln.remove(child)
            join = E.SubElement(ln, '{%s}%s' % (A, it['lineJoin']))
            if it['lineJoin'] == 'miter':
                join.set('lim', str(round(it['miterLimit'] * 100000)))
        if it['tag'] == 'text':
            for tag in ['rPr', 'defRPr', 'endParaRPr']:
                for run in s.findall('.//a:' + tag, NS):
                    for language in ['latin', 'ea', 'cs']:
                        font = run.find('a:' + language, NS)
                        if font is None:
                            font = E.SubElement(run, '{%s}%s' % (A, language))
                        font.set('typeface', it['typeface'])
        tree.remove(s)

    def bounds(its):
        boxes = []
        for i in its:
            x, y, w, h = [i[k] for k in ['x', 'y', 'width', 'height']]
            angle = math.radians(i.get('rotation', 0))
            bw = abs(w * math.cos(angle)) + abs(h * math.sin(angle))
            bh = abs(w * math.sin(angle)) + abs(h * math.cos(angle))
            boxes.append((x + w / 2 - bw / 2, y + h / 2 - bh / 2,
                          x + w / 2 + bw / 2, y + h / 2 + bh / 2))
        return [round(f(b[k] for b in boxes) * 9525)
                for k, f in enumerate([min, min, max, max])]

    def append_items(parent, its, depth):
        nonlocal next_id
        pos = 0
        while pos < len(its):
            it = its[pos]
            if len(it['groups']) <= depth:
                parent.append(shapes[it['id']])
                pos += 1
                continue
            name = it['groups'][depth]
            end = pos + 1
            while end < len(its) and its[end]['groups'][:depth + 1] == it['groups'][:depth + 1]:
                end += 1
            selected = its[pos:end]
            group = E.SubElement(parent, '{%s}grpSp' % P)
            nv = E.SubElement(group, '{%s}nvGrpSpPr' % P)
            E.SubElement(nv, '{%s}cNvPr' % P, id=str(next_id), name=name)
            next_id += 1
            E.SubElement(nv, '{%s}cNvGrpSpPr' % P)
            E.SubElement(nv, '{%s}nvPr' % P)
            props = E.SubElement(group, '{%s}grpSpPr' % P)
            xf = E.SubElement(props, '{%s}xfrm' % A)
            x, y, right, bottom = bounds(selected)
            wh = dict(cx=max(1, right - x), cy=max(1, bottom - y))
            # Identity group transform: the leaf coordinates remain in slide units.
            for tag, attributes in [('off', dict(x=x, y=y)), ('ext', wh),
                                    ('chOff', dict(x=x, y=y)), ('chExt', wh)]:
                E.SubElement(xf, '{%s}%s' % (A, tag), **{k: str(v) for k, v in attributes.items()})
            append_items(group, selected, depth + 1)
            pos = end

    append_items(tree, items, 0)
    files[slides[0]] = E.tostring(root, encoding='utf-8', xml_declaration=True)
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return {
        'slides': 1, 'native_shapes': len(items),
        'text_objects': sum(i['tag'] == 'text' for i in items),
        'groups': len(root.findall('.//p:grpSp', NS)),
        'images': len(root.findall('.//p:pic', NS)),
        'cubic_segments': len(root.findall('.//a:cubicBezTo', NS)),
        'fonts': sorted({i['typeface'] for i in items if i['tag'] == 'text'}),
        'scope': 'Native object and hierarchy counts; visual appearance and editor behavior require rendered review.'
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ['scene', 'input', 'output', 'stats']:
        parser.add_argument('--' + key, required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists() or args.stats.exists():
        parser.error('Output and stats must be new files.')
    result = convert(json.loads(args.scene.read_text()), args.input, args.output)
    args.stats.write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == '__main__':
    main()
