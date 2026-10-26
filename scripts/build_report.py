#!/usr/bin/env python3
"""Build a portable, offline SVG comparison report from a JSON manifest.

All manifest file paths are relative to the manifest file, not the working directory.
Default mode requires a bound review ledger and scan, and runs review_loop.py check.
--draft permits incomplete or missing review evidence, with a visible draft banner.
The builder never changes a ledger or invents a pass verdict.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

VERSION = '1.1'
STATES = {'pass', 'allowed_difference', 'open', 'reviewing', 'fix_required', 'uncertain'}
DONE = {'pass', 'allowed_difference'}
ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'assets' / 'comparison-report'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def string(value, name, required=False):
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(name + ' must be ' + ('a nonempty string' if required else 'a string'))
    return value


def strings(value, name):
    if not isinstance(value, list):
        raise ValueError(name + ' must be an array of strings')
    return [string(x, name) for x in value]


def path_value(base, value, name):
    path = (base / string(value, name, True)).resolve()
    if not path.is_file():
        raise ValueError(name + ' file does not exist: ' + str(path))
    return path


def raster_size(path):
    """Read common raster dimensions without optional imaging dependencies."""
    raw = path.read_bytes()
    if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw) >= 24:
        return struct.unpack('>II', raw[16:24])
    if raw[:6] in {b'GIF87a', b'GIF89a'} and len(raw) >= 10:
        return struct.unpack('<HH', raw[6:10])
    if raw.startswith(b'\xff\xd8'):
        pos = 2
        while pos+3 < len(raw):
            if raw[pos] != 255:
                pos += 1; continue
            while pos < len(raw) and raw[pos] == 255:
                pos += 1
            if pos >= len(raw):
                break
            marker = raw[pos]; pos += 1
            if marker in {0, 1, 0xd8, 0xd9} or 0xd0 <= marker <= 0xd7:
                continue
            length = int.from_bytes(raw[pos:pos+2], 'big')
            if length < 2 or pos+length > len(raw):
                break
            if marker in {0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf}:
                height,width=struct.unpack('>HH',raw[pos+3:pos+7]);return width,height
            pos += length
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        chunk=raw[12:16]
        if chunk==b'VP8X' and len(raw)>=30:
            return 1+int.from_bytes(raw[24:27],'little'),1+int.from_bytes(raw[27:30],'little')
        if chunk==b'VP8L' and len(raw)>=25 and raw[20]==47:
            n=int.from_bytes(raw[21:25],'little');return (n&0x3fff)+1,((n>>14)&0x3fff)+1
        if chunk==b'VP8 ' and len(raw)>=30 and raw[23:26]==b'\x9d\x01\x2a':
            w,h=struct.unpack('<HH',raw[26:30]);return w&0x3fff,h&0x3fff
    raise ValueError('Unsupported or malformed raster image: '+str(path))


def inspect_svg(path, canvas):
    """Do not publish active or nonportable SVG as a downloadable artifact."""
    source = path.read_text(encoding='utf-8')
    if '<!DOCTYPE' in source.upper() or '<!ENTITY' in source.upper():
        raise ValueError('final_svg may not contain a DTD or entity declarations')
    root = ET.fromstring(source)
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('final_svg is not an SVG document')
    viewbox = root.get('viewBox')
    if not viewbox:
        raise ValueError('final_svg needs an explicit viewBox for aligned comparison')
    nums = [float(v) for v in re.split(r'[\s,]+', viewbox.strip())]
    if len(nums) != 4 or not all(math.isfinite(n) for n in nums) or nums[2] <= 0 or nums[3] <= 0:
        raise ValueError('final_svg has an invalid viewBox')
    if abs((nums[2]/nums[3])/(canvas['width']/canvas['height']) - 1) > .001:
        raise ValueError('final_svg viewBox aspect ratio differs from canvas')
    for element in root.iter():
        tag = element.tag.split('}')[-1].lower()
        if tag in {'script', 'foreignobject', 'iframe', 'animate', 'animatetransform', 'set'}:
            raise ValueError('final_svg must be static and may not contain ' + tag)
        for key, value in element.attrib.items():
            attr = key.split('}')[-1].lower()
            if attr.startswith('on'):
                raise ValueError('final_svg may not contain event handlers')
            if attr == 'href' and not (value.startswith('#') or value.startswith(('data:image/png;', 'data:image/jpeg;', 'data:image/webp;'))):
                raise ValueError('final_svg has an external or unsupported href; embed or package it first')
        contents = ' '.join(element.attrib.values()) + (element.text or '')
        if re.search(r'@import\b', contents, re.I):
            raise ValueError('final_svg may not import external CSS')
        for match in re.finditer(r'url\(\s*[\'\"]?([^\)\'\"\s]+)', contents, re.I):
            if not match.group(1).startswith('#'):
                raise ValueError('final_svg has an external CSS url')


def validate(manifest, base):
    if manifest.get('version') != 1:
        raise ValueError('manifest.version must be 1')
    title = string(manifest.get('title'), 'title', True)
    canvas = manifest.get('canvas', {})
    if any(not isinstance(canvas.get(k), int) or isinstance(canvas.get(k), bool) or not 1 <= canvas[k] <= 100000 for k in ('width', 'height')):
        raise ValueError('canvas width and height must be positive integer pixels')
    paths = {key:path_value(base, manifest.get(key), key) for key in ('source', 'final_svg', 'final_render')}
    for key in ('before_render', 'assets_zip', 'ledger', 'scan'):
        if manifest.get(key):
            paths[key] = path_value(base, manifest[key], key)
    if ('ledger' in paths) != ('scan' in paths):
        raise ValueError('ledger and scan must be supplied together')
    inspect_svg(paths['final_svg'], canvas)
    for key in ('source','final_render','before_render'):
        if key in paths and raster_size(paths[key]) != (canvas['width'],canvas['height']):
            raise ValueError(key + ' pixel dimensions do not match canvas')
    regions = manifest.get('regions', [])
    if not isinstance(regions, list):
        raise ValueError('regions must be an array')
    ids = set()
    normalized = []
    for region in regions:
        rid = string(region.get('id'), 'region.id', True)
        if rid in ids:
            raise ValueError('duplicate stable region id: ' + rid)
        ids.add(rid)
        box = region.get('box_xyxy')
        if not isinstance(box, list) or len(box) != 4 or any(not isinstance(n, (int, float)) or isinstance(n, bool) or not math.isfinite(n) for n in box):
            raise ValueError(rid + ': box_xyxy requires four finite pixel coordinates')
        x, y, right, bottom = box
        if not (0 <= x < right <= canvas['width'] and 0 <= y < bottom <= canvas['height']):
            raise ValueError(rid + ': box must be within the canvas')
        verdict = region.get('verdict', 'uncertain')
        if verdict not in STATES:
            raise ValueError(rid + ': unknown verdict')
        normalized.append({'id':rid, 'ledger_id':string(region.get('ledger_id',rid),'region.ledger_id',True), 'title':string(region.get('title', rid), 'region.title'), 'box_xyxy':box, 'verdict':verdict, 'summary':string(region.get('summary', ''), 'region.summary'), 'note':string(region.get('note', ''), 'region.note')})
    steps = []
    if not isinstance(manifest.get('steps', []), list):
        raise ValueError('steps must be an array')
    for index, step in enumerate(manifest.get('steps', [])):
        value = {'title':string(step.get('title'), 'step.title', True), 'detail':string(step.get('detail'), 'step.detail', True)}
        if step.get('image'):
            paths['step_' + str(index)] = path_value(base, step['image'], 'step.image')
            raster_size(paths['step_' + str(index)])
            value['image_key'] = 'step_' + str(index)
            value['caption'] = string(step.get('caption', ''), 'step.caption')
        steps.append(value)
    return {'title':title, 'summary':string(manifest.get('summary', ''), 'summary'), 'canvas':canvas, 'regions':normalized, 'steps':steps, 'allowed_changes':strings(manifest.get('allowed_changes', []), 'allowed_changes'), 'limitations':strings(manifest.get('limitations', []), 'limitations')}, paths


def review(paths, data, draft, base):
    result = {'complete':False, 'mode':'draft' if draft else 'release', 'scope':'Review records, final rediscovery, and file consistency; does not prove semantic completeness.'}
    try:
        if 'ledger' not in paths:
            raise ValueError('No ledger and scan are bound.')
        scan = json.loads(paths['scan'].read_text(encoding='utf-8'))
        ledger = json.loads(paths['ledger'].read_text(encoding='utf-8'))
        if scan.get('canvas') != [data['canvas']['width'],data['canvas']['height']]:
            raise ValueError('Report canvas does not match the scan canvas.')
        if sha(paths['source']) != scan['reference_sha256'] or sha(paths['final_render']) != scan['candidate_sha256']:
            raise ValueError('Report source / final render do not match the scan bindings.')
        if sha(paths['final_svg']) != ledger.get('artifact_sha256'):
            raise ValueError('Report SVG does not match the ledger binding.')
        by_id = {item['id']:item for item in ledger['items']}
        for region in data['regions']:
            item = by_id.get(region['ledger_id'])
            if not item or region['verdict'] not in DONE or item['state'] != region['verdict']:
                raise ValueError('Region status is unresolved or inconsistent with the ledger: ' + region['id'])
            x, y, r, b = region['box_xyxy']
            ix, iy, ir, ib = item['box_xyxy']
            if not (ix <= x < r <= ir and iy <= y < b <= ib):
                raise ValueError('Report region extends beyond the corresponding ledger region: ' + region['id'])
        command = [sys.executable, str(ROOT/'scripts'/'review_loop.py'), 'check', '--ledger', str(paths['ledger']), '--scan', str(paths['scan']), '--artifact', str(paths['final_svg'])]
        checked = subprocess.run(command, capture_output=True, text=True, cwd=base)
        result['gate_stdout'] = checked.stdout.strip()
        result['gate_stderr'] = checked.stderr.strip()
        if checked.returncode != 0:
            raise ValueError('review_loop.py check rejected delivery: ' + (checked.stderr.strip() or checked.stdout.strip()))
        result['gate'] = json.loads(checked.stdout)
        if result['gate'].get('complete') is not True:
            raise ValueError('The review gate did not confirm acceptance.')
        result['complete'] = not draft
        result['reason'] = 'Explicit draft mode; even if the gate passes, this is not marked as a release.' if draft else ''
    except (ValueError, KeyError, TypeError, OSError) as exc:
        result['reason'] = str(exc)
        if not draft:
            raise ValueError(str(exc) + '\nFor preview only, use --draft; the report will clearly state that visual acceptance is incomplete.') from exc
    return result


def copy_exact_viewer(scan, destination):
    """Bundle the complete inventory; do not require the reviewer to remember a link."""
    if not scan.get('exact'):
        return None  # Legacy report remains readable.
    from review_loop import validate_exact_inventory
    validate_exact_inventory(scan)
    source = Path(scan['exact']['manifest'])
    manifest = json.loads(source.read_text(encoding='utf-8'))
    target = destination/'exact'; target.mkdir()
    for entry in manifest['files'].values():
        name = entry['path']
        if Path(name).name != name:
            raise ValueError('Exact inventory assets must use flat relative filenames')
        shutil.copy2(source.parent/name, target/name)
    shutil.copy2(source,target/'manifest.json')
    encoded = json.dumps(manifest,ensure_ascii=False).replace('<','\\u003c')
    page = (ROOT/'assets/difference-viewer/index.html').read_text(encoding='utf-8')
    (target/'index.html').write_text(page.replace('__SCAN_DATA__',encoded),encoding='utf-8')
    return 'exact/index.html'


def copy_independent_evidence(ledger, destination, expected_binding=None):
    """Freeze the accepted whole-image review and current per-issue rechecks."""
    import independent_review
    checked = independent_review.check(ledger)
    if expected_binding is not None and checked['binding'] != expected_binding:
        raise ValueError('Independent acceptance changed while packaging')
    g = ledger['independent_review']
    wanted = {g['reviews'][-1]['id']} | {i['resolutions'][-1]['review_id'] for i in g['issues']}
    target = destination / 'audit' / 'independent-review'
    target.mkdir()
    frozen = {'version': 1, 'check': checked, 'known_issues': g['issues'], 'reviews': []}
    for row in g['reviews']:
        if row['id'] not in wanted:
            continue
        packet = independent_review.read(row['packet'])
        name = 'review-' + str(row['id'])
        packet_name = name + '-packet.json'
        shutil.copy2(row['packet'], target / packet_name)
        if sha(target / packet_name) != row['packet_sha256']:
            raise ValueError('Independent packet changed while packaging')
        def copy_image(image):
            image_name = image['sha256'] + Path(image['path']).suffix
            if not (target / image_name).exists():
                shutil.copy2(image['path'], target / image_name)
            if sha(target / image_name) != image['sha256']:
                raise ValueError('Independent image evidence changed while packaging')
            return image_name
        images = {label: copy_image(image) for label, image in packet['images'].items()}
        views = {label: copy_image(view) for label, view in packet.get('views', {}).items()}
        report_name = name + '-report.json'
        (target / report_name).write_text(json.dumps(row['report'], ensure_ascii=False, indent=2), encoding='utf-8')
        frozen['reviews'].append({'id': row['id'], 'phase': row['phase'], 'packet': packet_name,
                                  'packet_sha256': row['packet_sha256'], 'report': report_name,
                                  'report_content_sha256': row['report_sha256'], 'images': images,
                                  **({'views': views} if views else {})})
    index = target / 'index.json'
    index.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding='utf-8')
    return index.relative_to(destination).as_posix()


def make_report(args):
    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    data, paths = validate(manifest, manifest_path.parent)
    checked = review(paths, data, args.draft, manifest_path.parent)
    destination = args.out.resolve()
    if destination.exists():
        raise ValueError('Output already exists; use a new output directory: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.'+destination.name+'-', dir=destination.parent))
    try:
        media = temp/'media';media.mkdir()
        audit = temp/'audit';audit.mkdir()
        files = {}
        names = {'source':'source', 'final_svg':'final', 'final_render':'final-render', 'before_render':'before', 'assets_zip':'assets'}
        for key, path in paths.items():
            if key in {'scan', 'ledger'}:
                shutil.copy2(path, audit/(key+'.json'))
                continue
            extension = '.svg' if key == 'final_svg' else path.suffix.lower()
            allowed = {'.png','.jpg','.jpeg','.webp','.gif','.svg','.zip'}
            if extension not in allowed:
                raise ValueError(key + ': unsupported extension: ' + extension)
            target = media/(names.get(key,key)+extension)
            shutil.copy2(path, target)
            files[key] = target.relative_to(temp).as_posix()
        if 'scan' in paths:
            exact_link=copy_exact_viewer(json.loads(paths['scan'].read_text(encoding='utf-8')),temp)
            if exact_link:files['exact_viewer']=exact_link
        if checked['complete']:
            binding = checked['gate']['independent_review']['binding']
            for key, bound in [('source', 'reference_sha256'), ('final_render', 'candidate_sha256'), ('final_svg', 'artifact_sha256')]:
                if sha(temp / files[key]) != binding[bound]:
                    raise ValueError('Packaged ' + key + ' changed after independent acceptance')
            files['independent_review'] = copy_independent_evidence(json.loads(paths['ledger'].read_text(encoding='utf-8')), temp, binding)
        for step in data['steps']:
            if 'image_key' in step:
                step['image'] = files.pop(step.pop('image_key'))
        files['review_check'] = 'audit/review-check.json'
        (temp/files['review_check']).write_text(json.dumps(checked,ensure_ascii=False,indent=2), encoding='utf-8')
        data.update(files=files,review=checked,template_version=VERSION,created_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'))
        # Escaping < prevents literal </script>; text strings are only rendered via textContent.
        encoded = json.dumps(data,ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
        html = (TEMPLATES/'report.html').read_text(encoding='utf-8')
        html = html.replace('/*__STYLE__*/',(TEMPLATES/'report.css').read_text(encoding='utf-8')).replace('/*__SCRIPT__*/',(TEMPLATES/'report.js').read_text(encoding='utf-8')).replace('/*__DATA__*/',encoded)
        (temp/'index.html').write_text(html,encoding='utf-8')
        # File hashes make the packaged report's inputs auditable without rewriting the ledger.
        snapshot = {'manifest':manifest, 'input_sha256':{key:sha(path) for key,path in paths.items()}, 'note':'Frozen audit copies retain original evidence paths; the offline report works after relocation. Re-running review_loop requires the original evidence files.'}
        (audit/'manifest-snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        temp.rename(destination)
        return {'report':str(destination/'index.html'),'complete':checked['complete'],'draft':args.draft,'regions':len(data['regions'])}
    except BaseException:
        shutil.rmtree(temp,ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__,epilog='Example: python build_report.py --manifest report.json --out delivery-report\nPreview: add --draft. Open OUT/index.html directly; retain the whole directory.',formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--manifest',type=Path,required=True,help='JSON manifest; paths resolve from its containing directory')
    parser.add_argument('--out',type=Path,required=True,help='New output directory (must not already exist)')
    parser.add_argument('--draft',action='store_true',help='Permit missing/incomplete review evidence; visibly mark report as not visually accepted')
    args = parser.parse_args()
    try:
        print(json.dumps(make_report(args),ensure_ascii=False))
    except (ValueError,KeyError,TypeError,OSError,ET.ParseError) as exc:
        parser.exit(2,str(exc)+'\n')


if __name__ == '__main__':
    main()
