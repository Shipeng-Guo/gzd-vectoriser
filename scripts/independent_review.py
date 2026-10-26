#!/usr/bin/env python3
"""Mandatory independent visual-review bookkeeping, not a visual correctness oracle.

A packet deliberately contains no maker observations or previous pass claims. The
recheck phase exposes only known finding details. Identity/inspection attestations
are supplied by the operator; this tool cannot prove who looked at an image.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import tempfile
import time

VERSION = 1
FINAL = {'fixed', 'rejected', 'allowed_difference'}
GENERIC = {'pass', 'passed', 'ok', 'okay', 'looks good', 'all good', 'no issues',
           'matches source', 'reviewed', 'done', 'fixed', 'rejected', '\u901a\u8fc7', '\u5df2\u68c0\u67e5', '\u6b63\u5e38', '\u65e0\u5dee\u5f02', '\u4e00\u81f4'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, delete=False) as out:
            tmp = Path(out.name)
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


def note(value):
    if not isinstance(value, str) or not value.strip() or value.strip().lower().strip(' .。!！') in GENERIC:
        raise ValueError('Independent review needs a concrete image observation, not a blanket pass')
    return value


def gate(j):
    value = j.get('independent_review')
    if not value or value.get('version') != VERSION or value.get('required') is not True:
        raise ValueError('Mandatory independent visual review is missing; migrate with independent_review.py attach --maker-id ID')
    return value


def attach(j, maker_id='artifact-maker'):
    if j.get('independent_review'):
        raise ValueError('Independent review already attached; history cannot be replaced')
    if not isinstance(maker_id, str) or not maker_id.strip():
        raise ValueError('maker_id must identify the artifact author/session')
    j['version'] = max(5, j.get('version', 0))
    j['independent_review'] = {'version': VERSION, 'required': True, 'maker_id': maker_id,
                               'revision': 0, 'issues': [], 'reviews': []}
    # Import failures, even if the maker subsequently marked the region passed.
    for item in j.get('items', []):
        failures = [h for h in item.get('history', []) if h.get('verdict') in {'fix_required', 'uncertain'}]
        if failures:
            for failure in failures:
                track_local(j, item, failure)
        elif item.get('state') in {'fix_required', 'uncertain'} or item.get('pending_fix'):
            track_local(j, item, {'note': 'Unresolved region inherited during explicit migration.',
                                  'evidence': item.get('evidence')})


def bounds(box, canvas):
    if not isinstance(box, list) or len(box) != 4 or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in box):
        raise ValueError('Finding requires four finite box_xyxy coordinates')
    if not (0 <= box[0] < box[2] <= canvas[0] and 0 <= box[1] < box[3] <= canvas[1]):
        raise ValueError('Finding box is outside the source canvas')


def add_issue(j, issue_id, title, box, observation, origin, evidence):
    g = gate(j)
    bounds(box, j['canvas'])
    existing = next((i for i in g['issues'] if i['id'] == issue_id), None)
    event = {'note': observation, 'origin': origin, 'evidence': copy.deepcopy(evidence),
             'artifact_sha256': j.get('artifact_sha256'), 'candidate_sha256': j.get('candidate_sha256'),
             'recorded_at_ns': time.time_ns()}
    if existing:
        if existing['box_xyxy'] != box:
            raise ValueError('A stable known issue cannot change its box: ' + issue_id)
        existing['occurrences'].append(event)
    else:
        g['issues'].append({'id': issue_id, 'title': title, 'box_xyxy': copy.deepcopy(box),
                            'occurrences': [event], 'resolutions': []})
    g['revision'] += 1


def track_local(j, item, observation):
    """Preserve each maker-reported failure; maker passes never resolve this registry."""
    if not j.get('independent_review'):
        return  # Legacy workflows remain editable, but cannot pass the new check.
    evidence = {k: observation[k] for k in ('evidence', 'evidence_sha256') if observation.get(k)}
    add_issue(j, 'local:' + item['id'], item.get('name', item['id']), item['box_xyxy'],
              observation.get('note', 'Unresolved local visual finding.'), 'local', evidence)


def context(j):
    gate(j)
    for key in ('reference', 'candidate', 'artifact'):
        if not j.get(key) or not j.get(key + '_sha256'):
            raise ValueError('Independent review requires source, current render and artifact bindings: ' + key)
        if sha(j[key]) != j[key + '_sha256']:
            raise ValueError(key + ' changed; rescan/rebase before independent review')
    canvas = j.get('canvas')
    if not isinstance(canvas, list) or len(canvas) != 2 or any(type(x) is not int or x < 1 for x in canvas):
        raise ValueError('Independent review requires the current canvas')
    requirements = []
    for item in j.get('items', []):
        bounds(item['box_xyxy'], canvas)
        req = item.get('requirements', {})
        if req:
            if not isinstance(req, dict) or any(not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip() for k, v in req.items()):
                raise ValueError('Invalid source requirements')
            requirements.append({'id': 'requirement:' + item['id'], 'box_xyxy': item['box_xyxy'], 'requirements': req})
    # Every fixed review box is bound, even boxes without semantic requirements.
    scope = {'canvas': canvas, 'regions': [{'id': i['id'], 'box_xyxy': i['box_xyxy'],
                                          'requirements': i.get('requirements', {})} for i in j.get('items', [])],
             'policies': j.get('policies', [])}
    return {'reference_sha256': j['reference_sha256'], 'candidate_sha256': j['candidate_sha256'],
            'artifact_sha256': j['artifact_sha256'], 'scope_sha256': fingerprint(scope)}, requirements


def coverage(j, requirements):
    w, h = j['canvas']
    rows = [{'id': 'whole', 'box_xyxy': [0, 0, w, h], 'requirements': {}}]
    # A deterministic full partition cannot lose a low-salience region by ranking.
    xs = sorted(set([0, w // 3, 2 * w // 3, w]))
    ys = sorted(set([0, h // 3, 2 * h // 3, h]))
    for y in range(len(ys)-1):
        for x in range(len(xs)-1):
            rows.append({'id': f'grid:{y+1}:{x+1}', 'box_xyxy': [xs[x], ys[y], xs[x+1], ys[y+1]], 'requirements': {}})
    return rows + copy.deepcopy(requirements)


def validate_png(path):
    """Structural views are inert, decodable still PNGs, never SVG/text claims."""
    path = Path(path)
    with path.open('rb') as stream:
        if stream.read(8) != b'\x89PNG\r\n\x1a\n':
            raise ValueError('Structural view must be a decodable PNG image: ' + str(path))
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError('Structural views require Pillow for PNG decoding; ordinary packets remain standard-library-only') from exc
    try:
        with Image.open(path) as image:
            if image.format != 'PNG' or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('Structural view must be a still PNG image')
            image.verify()
        with Image.open(path) as image:
            image.load()
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError('Structural view is not a valid decodable PNG: ' + str(path)) from exc


def prepare_views(rows, binding, base=None):
    if rows is None:
        return {}
    if not isinstance(rows, list):
        raise ValueError('--views requires a JSON array of structural view descriptions')
    views = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'path', 'artifact_sha256', 'description'}:
            raise ValueError('Each structural view needs only id, path, artifact_sha256 and description')
        key = row['id']
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', key) or key in views:
            raise ValueError('Structural view IDs must be unique safe identifiers')
        if row['artifact_sha256'] != binding['artifact_sha256']:
            raise ValueError('Structural view artifact_sha256 is stale or does not match the current artifact: ' + key)
        note(row['description'])
        if not isinstance(row['path'], str) or not row['path'].strip():
            raise ValueError('Structural view requires an image path: ' + key)
        path = ((Path(base) if base else Path.cwd()) / row['path']).resolve()
        validate_png(path)
        views[key] = {'path': str(path), 'sha256': sha(path),
                      'artifact_sha256': row['artifact_sha256'], 'description': row['description']}
    return views


def packet(j, phase, destination, views=None, views_base=None):
    g = gate(j)
    binding, requirements = context(j)
    if phase == 'recheck' and not g['issues']:
        raise ValueError('No known issues to recheck; request a discovery packet')
    structural = prepare_views(views, binding, views_base)
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Packet output already exists; use a fresh directory')
    destination.mkdir(parents=True)
    try:
        images = {}
        for label, key in [('source', 'reference'), ('candidate', 'candidate')]:
            path = destination / (label + Path(j[key]).suffix)
            shutil.copyfile(j[key], path)
            images[label] = {'path': str(path), 'sha256': sha(path)}
        for key, view in structural.items():
            path = destination / ('view-' + key + '.png')
            shutil.copyfile(view['path'], path)
            if sha(path) != view['sha256']:
                raise ValueError('Structural view changed while creating reviewer packet: ' + key)
            view['path'] = str(path)
        p = {'version': VERSION, 'phase': phase, 'binding': binding, 'revision': g['revision'],
             'created_at_ns': time.time_ns(), 'canvas': j['canvas'], 'images': images,
             'instructions': 'Inspect source and current render directly. Record concrete observations for every coverage region and requirement. Report every visible error or uncertainty. Tool checks bookkeeping only; it does not establish visual correctness or reviewer independence.',
             'coverage': coverage(j, requirements) if phase == 'discovery' else [],
             'preauthorized_policies': copy.deepcopy(j.get('policies', []))}
        if structural:
            p['views'] = structural
            p['instructions'] += ' Structural views are current-artifact observation images, not approval claims; cite a relevant view as view:ID alongside source and candidate.'
        if phase == 'recheck':
            p['known_issues'] = [{'id': i['id'], 'title': i['title'], 'box_xyxy': i['box_xyxy'],
                                  'observations': [o['note'] for o in i['occurrences']]} for i in g['issues']]
        validate_images(p)
        path = destination / 'packet.json'
        save(path, p)
        template = {'packet_sha256': sha(path), 'reviewer_id': '', 'independence_attestation': False,
                    'coverage': [{'id': c['id'], 'verdict': '', 'note': '', 'evidence': ['source', 'candidate'],
                                  **({'checks': {k: {'verdict': '', 'note': ''} for k in c['requirements']}} if c['requirements'] else {})} for c in p['coverage']],
                    'findings': [], 'resolutions': [{'id': i['id'], 'verdict': '', 'note': '', 'evidence': ['source', 'candidate']} for i in p.get('known_issues', [])]}
        save(destination / 'report-template.json', template)
        return path
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def validate_packet(p, j):
    binding, req = context(j)
    allowed = {'version', 'phase', 'binding', 'revision', 'created_at_ns', 'canvas', 'images', 'instructions', 'coverage', 'preauthorized_policies'}
    if p.get('phase') == 'recheck':
        allowed.add('known_issues')
    if 'views' in p:
        allowed.add('views')
    if set(p) != allowed:
        raise ValueError('Reviewer packet contains missing fields or unauthorized narrative/history')
    if p.get('version') != VERSION or p.get('phase') not in {'discovery', 'recheck'}:
        raise ValueError('Invalid independent reviewer packet')
    if p.get('binding') != binding or p.get('revision') != gate(j)['revision']:
        raise ValueError('Independent review packet is stale after artifact, coverage, policy or issue changes')
    if p.get('canvas') != j['canvas'] or p.get('preauthorized_policies') != j.get('policies', []):
        raise ValueError('Reviewer packet scope does not match the current obligations')
    expected = coverage(j, req) if p['phase'] == 'discovery' else []
    if p.get('coverage') != expected:
        raise ValueError('Reviewer packet has missing or changed coverage')
    if p['phase'] == 'discovery' and 'known_issues' in p:
        raise ValueError('Fresh discovery packet cannot include known issues or prior verdicts')
    if p['phase'] == 'recheck':
        expected_issues = [{'id': i['id'], 'title': i['title'], 'box_xyxy': i['box_xyxy'],
                            'observations': [o['note'] for o in i['occurrences']]} for i in gate(j)['issues']]
        if p.get('known_issues') != expected_issues:
            raise ValueError('Recheck packet must retain every known finding')
    validate_images(p)


def validate_images(p):
    images = p.get('images', {})
    if set(images) != {'source', 'candidate'}:
        raise ValueError('Source and current render evidence are both required')
    for label, key in [('source', 'reference_sha256'), ('candidate', 'candidate_sha256')]:
        image = images[label]
        if image.get('sha256') != p['binding'][key] or sha(image['path']) != image['sha256']:
            raise ValueError('Independent image evidence is missing, stale or changed: ' + label)


    views = p.get('views', {})
    if not isinstance(views, dict):
        raise ValueError('Structural packet views must be keyed by view ID')
    for key, view in views.items():
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,63}', key) or
                not isinstance(view, dict) or set(view) != {'path', 'sha256', 'artifact_sha256', 'description'}):
            raise ValueError('Invalid structural view metadata')
        note(view['description'])
        if view['artifact_sha256'] != p['binding']['artifact_sha256']:
            raise ValueError('Structural view artifact binding is stale: ' + key)
        if sha(view['path']) != view['sha256']:
            raise ValueError('Structural view evidence is missing, stale or changed: ' + key)
        validate_png(view['path'])


def evidence(row, packet):
    refs = row.get('evidence')
    if not isinstance(refs, list) or refs[:2] != ['source', 'candidate']:
        raise ValueError('Each observation/resolution must cite both current packet images: source, candidate')
    available = {'view:' + key for key in packet.get('views', {})}
    if any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs) or any(ref not in available for ref in refs[2:]):
        raise ValueError('Evidence contains an unknown, duplicate or unregistered structural view reference')
    note(row.get('note'))


def policy_allows(j, issue, policy_id):
    p = next((p for p in j.get('policies', []) if p.get('id') == policy_id), None)
    if not p or not p.get('reason') or not p.get('allowed_changes') or not p.get('invariants'):
        return False
    a, b = issue['box_xyxy'], p.get('box_xyxy', [])
    if len(b) != 4 or not (b[0] <= a[0] < a[2] <= b[2] and b[1] <= a[1] < a[3] <= b[3]):
        return False
    return not any(min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1]) for b in p.get('strict_boxes', []))


def record(j, packet_path, report):
    """Return a copy; malformed batches never partially resolve or drop findings."""
    j = copy.deepcopy(j)
    g = gate(j)
    p = read(packet_path)
    validate_packet(p, j)
    if report.get('packet_sha256') != sha(packet_path):
        raise ValueError('Report must bind the exact reviewer packet SHA-256')
    reviewer = report.get('reviewer_id')
    if not isinstance(reviewer, str) or not reviewer.strip() or reviewer == g['maker_id'] or report.get('independence_attestation') is not True:
        raise ValueError('A reviewer distinct from the maker must attest independent image inspection')
    if set(report) != {'packet_sha256', 'reviewer_id', 'independence_attestation', 'coverage', 'findings', 'resolutions'}:
        raise ValueError('Report requires explicit coverage, findings and resolutions arrays; no blanket verdict')
    if any(not isinstance(report[k], list) for k in ('coverage', 'findings', 'resolutions')):
        raise ValueError('coverage, findings and resolutions must be arrays')
    observed = report['coverage']
    if [c.get('id') for c in observed] != [c['id'] for c in p['coverage']]:
        raise ValueError('Missing, duplicate, reordered or unknown independent coverage rows')
    notes = set()
    for row, required in zip(observed, p['coverage']):
        evidence(row, p)
        normalized = row['note'].strip().casefold()
        if normalized in notes:
            raise ValueError('Coverage needs a distinct region-specific observation in every row')
        notes.add(normalized)
        if row.get('verdict') not in {'pass', 'fix_required', 'uncertain'}:
            raise ValueError('Coverage needs pass, fix_required or uncertain verdict')
        checks = row.get('checks', {})
        if set(checks) != set(required['requirements']):
            raise ValueError('Missing or unknown source requirement checks')
        for check in checks.values():
            note(check.get('note'))
            if check.get('verdict') not in {'pass', 'fail', 'uncertain'} or (row['verdict'] == 'pass' and check['verdict'] != 'pass'):
                raise ValueError('Unresolved source requirement blocks a coverage pass')
    for finding in report['findings']:
        evidence(finding, p)
        note(finding.get('title'))
        bounds(finding.get('box_xyxy'), j['canvas'])
    if any(c['verdict'] != 'pass' for c in observed) and not report['findings']:
        raise ValueError('Failed or uncertain coverage must register concrete persistent findings')
    if p['phase'] == 'discovery' and report['resolutions']:
        raise ValueError('Fresh discovery cannot resolve known findings; use a dedicated recheck')
    expected_ids = [i['id'] for i in p.get('known_issues', [])]
    if [r.get('id') for r in report['resolutions']] != expected_ids:
        raise ValueError('Every known issue needs its own explicit current-image resolution')
    review_id = len(g['reviews']) + 1
    for resolution, issue in zip(report['resolutions'], g['issues']):
        evidence(resolution, p)
        if resolution.get('verdict') not in FINAL | {'unresolved'}:
            raise ValueError('Known finding needs fixed, rejected, allowed_difference or unresolved')
        if resolution['verdict'] == 'allowed_difference' and not policy_allows(j, issue, resolution.get('policy_id')):
            raise ValueError('Allowed difference requires an existing policy covering this finding and respecting strict regions')
        issue['resolutions'].append(dict(copy.deepcopy(resolution), binding=copy.deepcopy(p['binding']),
                                          occurrence_count=len(issue['occurrences']), review_id=review_id))
    for finding in report['findings']:
        issue_id = 'I' + str(1 + sum(i['id'].startswith('I') for i in g['issues'])).zfill(6)
        add_issue(j, issue_id, finding['title'], finding['box_xyxy'], finding['note'],
                  'independent', {'packet': str(Path(packet_path).resolve()), 'packet_sha256': sha(packet_path)})
    review = {'id': review_id, 'phase': p['phase'], 'binding': p['binding'],
              'packet': str(Path(packet_path).resolve()), 'packet_sha256': sha(packet_path),
              'report': copy.deepcopy(report), 'report_sha256': fingerprint(report),
              'recorded_at_ns': time.time_ns(), 'revision': g['revision'],
              'clean': p['phase'] == 'discovery' and not report['findings'] and all(c['verdict'] == 'pass' for c in observed)}
    if p['phase'] == 'recheck':
        g['revision'] += 1  # A discovery prepared before recheck cannot close the loop.
        review['revision'] = g['revision']
    g['reviews'].append(review)
    return j


def check(j):
    g = gate(j)
    binding, _ = context(j)
    for issue in g['issues']:
        if not issue['resolutions']:
            raise ValueError('Known issue has no independent resolution: ' + issue['id'])
        resolution = issue['resolutions'][-1]
        if (resolution['verdict'] not in FINAL or resolution['binding'] != binding or
                resolution['occurrence_count'] != len(issue['occurrences'])):
            raise ValueError('Known issue is unresolved or its evidence is stale: ' + issue['id'])
        if resolution['verdict'] == 'allowed_difference' and not policy_allows(j, issue, resolution.get('policy_id')):
            raise ValueError('Known issue no longer has a valid allowed-difference policy: ' + issue['id'])
        review = next((r for r in g['reviews'] if r['id'] == resolution['review_id']), None)
        if not review or review['phase'] != 'recheck':
            raise ValueError('Resolution has no independent recheck provenance: ' + issue['id'])
        original = next((r for r in review['report']['resolutions'] if r['id'] == issue['id']), None)
        recorded = {k: v for k, v in resolution.items() if k not in {'binding', 'occurrence_count', 'review_id'}}
        if original != recorded:
            raise ValueError('Resolution disagrees with its independent reviewer report: ' + issue['id'])
        verify_record(review, binding)
    if not g['reviews']:
        raise ValueError('Fresh independent whole-image discovery is required')
    last = g['reviews'][-1]
    if (not last['clean'] or last['phase'] != 'discovery' or last['revision'] != g['revision'] or
            last['report']['findings'] or any(c.get('verdict') != 'pass' for c in last['report']['coverage'])):
        raise ValueError('Fresh clean independent whole-image discovery is required after all findings and rechecks')
    verify_record(last, binding)
    validate_packet(read(last['packet']), j)
    return {'complete': True, 'known_issues': len(g['issues']), 'review_id': last['id'],
            'reviewer_id': last['report']['reviewer_id'], 'binding': binding,
            'scope': 'Current hashes, declared coverage, persistent findings and independent-review attestations checked; visual correctness and actual independence are not mechanically proven.'}


def verify_record(review, binding):
    if review['binding'] != binding:
        raise ValueError('Independent review is stale for current artifact/render/source/coverage')
    if sha(review['packet']) != review['packet_sha256'] or fingerprint(review['report']) != review['report_sha256']:
        raise ValueError('Independent review record or packet changed')
    validate_images(read(review['packet']))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['attach', 'packet', 'record', 'flag', 'check', 'status'])
    ap.add_argument('--ledger', type=Path, required=True)
    ap.add_argument('--maker-id')
    ap.add_argument('--phase', choices=['discovery', 'recheck'])
    ap.add_argument('--output', type=Path)
    ap.add_argument('--packet', type=Path)
    ap.add_argument('--report', type=Path)
    ap.add_argument('--findings', type=Path)
    ap.add_argument('--views', type=Path, help='Optional JSON structural PNG views; paths are relative to this JSON file')
    args = ap.parse_args()
    try:
        j = read(args.ledger)
        if args.action == 'attach':
            if not args.maker_id:
                raise ValueError('Legacy migration requires explicit --maker-id')
            attach(j, args.maker_id)
            save(args.ledger, j)
            result = {'attached': True, 'known_issues': len(gate(j)['issues'])}
        elif args.action == 'packet':
            if not args.phase or not args.output:
                raise ValueError('packet requires --phase and fresh --output directory')
            result = {'packet': str(packet(j, args.phase, args.output, views=read(args.views) if args.views else None, views_base=args.views.resolve().parent if args.views else None))}
        elif args.action == 'record':
            if not args.packet or not args.report:
                raise ValueError('record requires --packet and --report')
            updated = record(j, args.packet, read(args.report))
            save(args.ledger, updated)
            result = {'recorded': gate(updated)['reviews'][-1]['id'], 'known_issues': len(gate(updated)['issues'])}
        elif args.action == 'flag':
            context(j)
            rows = read(args.findings) if args.findings else None
            if not isinstance(rows, list) or not rows:
                raise ValueError('flag needs --findings with a nonempty array')
            for row in rows:
                note(row.get('note')); note(row.get('title'))
                if not isinstance(row.get('id'), str) or not row['id'].strip():
                    raise ValueError('External finding needs a stable id')
                path = Path(row['evidence']).resolve()
                add_issue(j, 'external:' + row['id'], row['title'], row['box_xyxy'], row['note'],
                          'external', {'path': str(path), 'sha256': sha(path)})
            save(args.ledger, j)
            result = {'known_issues': len(gate(j)['issues'])}
        elif args.action == 'status':
            g = gate(j)
            result = {'required': True, 'maker_id': g['maker_id'], 'reviews': len(g['reviews']),
                      'known_issues': [{'id': i['id'], 'title': i['title'], 'resolutions': len(i['resolutions'])} for i in g['issues']]}
        else:
            result = check(j)
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError) as exc:
        ap.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
