#!/usr/bin/env python3
"""Standard-library regression tests for review state and evidence binding.

These fixtures test bookkeeping, not image detection or semantic correctness.
All artifacts are temporary; no personal or project paths are required.
"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import independent_review

SCRIPT = Path(__file__).with_name('review_loop.py')
REQUIREMENTS = {
    'shape': 'The receptor outline is closed and has a narrow lower stem.',
    'labels': 'JAK1 is legible and unobstructed by receptor or arrow paths.',
    'connections': 'The arrow terminal touches the lower receptor stem.',
}
CHECKS = {
    'shape': {'verdict': 'pass', 'note': 'The receptor contour closes above its narrow stem.'},
    'labels': {'verdict': 'pass', 'note': 'All four JAK1 glyphs remain visible with clear space around them.'},
    'connections': {'verdict': 'pass', 'note': 'The arrow terminal meets the lower receptor stem at its center.'},
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Fixture:
    def __init__(self, root, count=1, policies=None, requirements=None):
        self.root = root
        self.count = count
        self.seq = 0
        self.requirements = requirements
        self.source = root / 'source.png'
        self.candidate = root / 'candidate.png'
        self.artifact = root / 'drawing.svg'
        self.ledger = root / 'ledger.json'
        self.source.write_bytes(b'opaque source fixture')
        self.artifact.write_text('<svg/>')
        self.write_scan()
        extra = []
        if policies is not None:
            policy_file = root / 'policies.json'
            policy_file.write_text(json.dumps(policies))
            extra = ['--policies', policy_file]
        self.call('init', *self.scan_args, *extra)

    @property
    def scan_args(self):
        return ['--scan', self.scan, '--artifact', self.artifact]

    def read(self):
        return json.loads(self.ledger.read_text())

    def write_scan(self, revision='one', ids=None):
        self.seq += 1
        self.candidate.write_bytes(('render ' + revision).encode())
        self.scan = self.root / f'scan_{self.seq}.json'
        self.pairs = []
        coverage = []
        for n in range(self.count):
            pair = self.root / f'pair_{self.seq}_{n}.png'
            # Identical crops produce identical canonical bytes across fresh scans.
            pair.write_bytes(f'pair {revision} region {n}'.encode())
            self.pairs.append(pair)
            coverage.append({
                'id': ids[n] if ids else f'coverage_{n + 1:02d}',
                'box_xyxy': [n * 50, 0, (n + 1) * 50, 50],
                'source_crop_sha256': f'source-crop-{n}',
                'candidate_crop_sha256': f'{revision}-crop-{n}',
                'evidence': str(pair), 'channel_signals': {},
            })
            if self.requirements and n == 0:
                coverage[-1]['requirements'] = self.requirements
        self.scan.write_text(json.dumps({
            'version': 3, 'run_id': f'run-{self.seq}',
            'started_at_ns': time.time_ns(), 'canvas': [100, 100],
            'reference': str(self.source), 'candidate': str(self.candidate),
            'reference_sha256': digest(self.source),
            'candidate_sha256': digest(self.candidate),
            'proposals': [], 'coverage': coverage, 'source_regions': [],
        }))

    def call(self, action, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), action, '--ledger', str(self.ledger),
             *map(str, args)], capture_output=True, text=True,
        )
        if (result.returncode == 0) != ok:
            raise AssertionError(f'{action}: {result.returncode}\n{result.stdout}{result.stderr}')
        return result

    def record(self, verdict='pass', index=0, evidence=None, extra=()):
        issue = self.read()['items'][index]
        self.call('begin', '--id', issue['id'])
        return self.call('record', '--id', issue['id'], '--verdict', verdict,
                         '--note', 'Observed current canonical region.',
                         '--evidence', evidence or issue['evidence'], *extra)

    def json_file(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data))
        return path

    def batch_rows(self):
        notes = ['Left receptor contour is closed; its lower stem has no gap.',
                 'Right arrow ends at the membrane edge without touching the label.']
        return [{'id': i['id'], 'verdict': 'pass', 'note': notes[n],
                 'evidence': i['evidence']} for n, i in enumerate(self.read()['items'])]

    def batch(self, rows, ok=True):
        return self.call('record-batch', '--observations',
                         self.json_file('observations.json', rows), ok=ok)

    def independent_pass(self):
        """Synthetic state-machine evidence only; never used for real visual approval."""
        j = self.read()
        for phase in (['recheck'] if j['independent_review']['issues'] else []) + ['discovery']:
            target = self.root / ('independent_' + str(time.time_ns()))
            packet = independent_review.packet(j, phase, target)
            report = independent_review.read(target / 'report-template.json')
            report.update(reviewer_id='synthetic-independent-reviewer', independence_attestation=True)
            for row in report['coverage']:
                row.update(verdict='pass', note='Synthetic bookkeeping observation for region ' + row['id'])
                for key, check in row.get('checks', {}).items():
                    check.update(verdict='pass', note='Synthetic bookkeeping expectation check: ' + key)
            for row in report['resolutions']:
                row.update(verdict='fixed', note='Synthetic current-image resolution for ' + row['id'])
            j = independent_review.record(j, packet, report)
        independent_review.save(self.ledger, j)

    def clean_discovery(self):
        for index in range(self.count):
            self.record(index=index)
        self.call('start-discovery', *self.scan_args)
        self.write_scan()
        self.call('rebase', *self.scan_args)
        for index in range(self.count):
            self.record(index=index)
        self.call('finish-discovery', *self.scan_args, '--note', 'Fresh whole-canvas review completed.')
        self.independent_pass()
        self.call('check', *self.scan_args)


class ReviewLoopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_inner_and_outer_loops(self):
        f = Fixture(self.root, count=2)
        f.record('fix_required')
        f.call('begin', '--id', 'coverage_02', ok=False)
        f.record()
        f.record(index=1)
        f.call('check', *f.scan_args, ok=False)
        f.call('start-discovery', *f.scan_args)
        f.call('rebase', *f.scan_args, ok=False)  # Old scan cannot satisfy discovery.
        f.write_scan()
        f.call('rebase', *f.scan_args)
        self.assertTrue(all(i['state'] == 'open' for i in f.read()['items']))
        f.call('finish-discovery', *f.scan_args, '--note', 'Not observed.', ok=False)
        f.record('fix_required')
        f.record()
        f.record(index=1)
        f.call('finish-discovery', *f.scan_args, '--note', 'Found a problem earlier.', ok=False)
        f.clean_discovery()
        self.assertEqual(f.read()['discovery']['round'], 2)
        f.artifact.write_text('<svg><path/></svg>')
        f.call('check', *f.scan_args, ok=False)

    def test_artifact_binding_cannot_be_dropped(self):
        f = Fixture(self.root)
        prior = f.ledger.read_bytes()
        f.write_scan('two')
        f.call('rebase', '--scan', f.scan, ok=False)
        self.assertEqual(f.ledger.read_bytes(), prior)
        self.assertEqual(f.read()['artifact_sha256'], digest(f.artifact))
        f.call('rebase', *f.scan_args)
        f.record()
        f.call('start-discovery', *f.scan_args)
        f.write_scan('two')
        prior = f.ledger.read_bytes()
        f.call('rebase', '--scan', f.scan, ok=False)
        self.assertEqual(f.ledger.read_bytes(), prior)
        f.call('rebase', *f.scan_args)

    def test_stale_unrelated_and_mutated_evidence_rejected(self):
        f = Fixture(self.root)
        old_pair = f.pairs[0]
        f.record('fix_required')
        f.artifact.write_text('<svg><path/></svg>')
        f.write_scan('repaired')
        f.call('rebase', *f.scan_args)
        unrelated = self.root / 'unrelated.png'
        unrelated.write_bytes(b'unrelated evidence')
        for evidence in (old_pair, unrelated):
            f.call('record', '--id', 'coverage_01', '--verdict', 'pass',
                   '--note', 'This must not clear the issue.', '--evidence', evidence, ok=False)
        self.assertTrue(f.read()['items'][0]['pending_fix'])
        self.assertEqual(f.read()['active'], 'coverage_01')
        canonical_copy = self.root / 'copy.png'
        canonical_copy.write_bytes(f.pairs[0].read_bytes())
        f.pairs[0].write_bytes(b'mutated canonical evidence')
        f.call('record', '--id', 'coverage_01', '--verdict', 'pass',
               '--note', 'Mutated canonical must fail.', '--evidence', canonical_copy, ok=False)
        f.write_scan('repaired')
        f.call('rebase', *f.scan_args)
        f.record(evidence=canonical_copy)  # Byte-identical copies are accepted.
        history = f.read()['items'][0]['history'][-1]
        self.assertEqual(history['scan_evidence_sha256'], digest(canonical_copy))

    def test_allowed_policy_bounds_and_strict_subregions(self):
        policy = {'id': 'display', 'box_xyxy': [0, 0, 100, 100],
                  'reason': 'User permitted illustrative texture changes.',
                  'allowed_changes': ['texture'], 'invariants': ['identity', 'position'],
                  'strict_boxes': [[60, 0, 100, 50]]}
        f = Fixture(self.root, count=2, policies=[policy])
        f.call('begin', '--id', 'coverage_01')
        unrelated = self.root / 'unrelated.png'
        unrelated.write_bytes(b'unrelated allowed image')
        base = ['--id', 'coverage_01', '--verdict', 'allowed_difference',
                '--note', 'Authorized texture variation.', '--policy-id', 'display']
        f.call('record', *base, '--evidence', unrelated, ok=False)
        f.call('record', *base, '--evidence', f.pairs[0])
        f.call('begin', '--id', 'coverage_02')
        f.call('record', '--id', 'coverage_02', '--verdict', 'allowed_difference',
               '--note', 'Strict overlap must not pass.', '--policy-id', 'display',
               '--evidence', f.pairs[1], ok=False)
        f.record(index=1)
        f.write_scan('two')
        f.call('rebase', *f.scan_args)
        self.assertEqual(f.read()['policies'], [policy])
        # Lack of policy authorization cannot turn a hard region into an exemption.
        f.call('begin', '--id', 'coverage_01')
        f.call('record', *base[:-1], 'missing_policy', '--evidence', f.pairs[0], ok=False)

    def test_export_regions_stable_unique_and_legacy_canvas(self):
        f = Fixture(self.root, count=2)
        output = self.root / 'regions.json'
        prior = f.ledger.read_bytes()
        f.call('export-regions', '--output', output, '--prefix', 'carry_')
        data = json.loads(output.read_text())
        self.assertEqual(data['canvas'], [100, 100])
        self.assertEqual(len({r['id'] for r in data['regions']}), 2)
        self.assertTrue(all(r['id'].startswith('carry_') for r in data['regions']))
        self.assertEqual([r['ledger_id'] for r in data['regions']], ['coverage_01', 'coverage_02'])
        self.assertEqual(f.ledger.read_bytes(), prior)
        f.call('export-regions', '--output', f.ledger, ok=False)
        f.call('export-regions', '--output', output, '--prefix', '../bad', ok=False)
        j = f.read()
        del j['canvas']
        f.ledger.write_text(json.dumps(j))
        f.call('export-regions', '--output', output, ok=False)
        f.call('export-regions', '--scan', f.scan, '--output', output)
        exported = json.loads(output.read_text())
        self.assertEqual(exported['canvas'], [100, 100])
        # Re-ranked IDs must not replace stable issue IDs matched by fixed boxes.
        f.write_scan(ids=['ranked_02', 'ranked_01'])
        f.call('rebase', *f.scan_args)
        self.assertEqual([i['id'] for i in f.read()['items']], ['coverage_01', 'coverage_02'])

    def test_legacy_history_remains_readable_new_records_are_strict(self):
        f = Fixture(self.root)
        f.clean_discovery()
        j = f.read()
        j['version'] = 2
        j.pop('canvas')
        j.pop('independent_review')
        for item in j['items']:
            item.pop('scan_evidence_sha256')
            for h in item['history']:
                for key in ('scan_evidence_sha256', 'source_crop_sha256', 'candidate_crop_sha256'):
                    h.pop(key, None)
        f.ledger.write_text(json.dumps(j))
        f.call('check', *f.scan_args, ok=False)
        unrelated = self.root / 'old_observation.png'
        unrelated.write_bytes(b'old unrelated observation')
        f.call('begin', '--id', 'coverage_01')
        f.call('record', '--id', 'coverage_01', '--verdict', 'pass',
               '--note', 'New observations must be bound.', '--evidence', unrelated, ok=False)
        f.record()
        self.assertIn('scan_evidence_sha256', f.read()['items'][0]['history'][-1])

    def test_requirements_missing_failed_and_uncertain_checks_block_pass(self):
        f = Fixture(self.root, requirements=REQUIREMENTS)
        f.call('begin', '--id', 'coverage_01')
        base = ['--id', 'coverage_01', '--verdict', 'pass', '--evidence', f.pairs[0],
                '--note', 'The receptor, JAK1 label and arrow were observed together.']
        invalid = [None, {'shape': CHECKS['shape']},
                   dict(CHECKS, labels={'verdict': 'fail', 'note': 'The receptor path crosses the JAK1 letters.'}),
                   dict(CHECKS, labels={'verdict': 'uncertain', 'note': 'The JAK1 first glyph is not clear at this crop size.'}),
                   dict(CHECKS, labels={'verdict': 'pass', 'note': 'Pass.'}),
                   dict(CHECKS, typo=CHECKS['shape'])]
        before = f.ledger.read_bytes()
        for checks in invalid:
            with self.subTest(checks=checks):
                extra = ['--checks', f.json_file('checks.json', checks)] if checks is not None else []
                f.call('record', *base, *extra, ok=False)
                self.assertEqual(f.ledger.read_bytes(), before)
        f.call('record', *base, '--checks', f.json_file('checks.json', CHECKS))
        h = f.read()['items'][0]['history'][-1]
        self.assertEqual(h['checks'], CHECKS)
        self.assertEqual(h['requirements'], REQUIREMENTS)
        self.assertEqual(h['candidate_crop_sha256'], 'one-crop-0')

    def test_repair_requires_fresh_complete_checks_and_export_retains_requirements(self):
        f = Fixture(self.root, requirements=REQUIREMENTS)
        f.record(extra=['--checks', f.json_file('checks.json', CHECKS)])
        f.record('fix_required')
        exported = self.root / 'fixed.json'
        f.call('export-regions', '--output', exported)
        self.assertEqual(json.loads(exported.read_text())['regions'][0]['requirements'], REQUIREMENTS)
        f.artifact.write_text('<svg><path id="repaired"/></svg>')
        # Even an older exporter omitting expectations cannot silently clear them.
        f.requirements = None
        f.write_scan('repaired')
        f.call('rebase', *f.scan_args)
        self.assertEqual(f.read()['items'][0]['requirements'], REQUIREMENTS)
        before = f.ledger.read_bytes()
        base = ['--id', 'coverage_01', '--verdict', 'pass', '--evidence', f.pairs[0],
                '--note', 'The moved receptor no longer crosses JAK1.']
        f.call('record', *base, ok=False)
        partial = {'shape': CHECKS['shape'], 'connections': CHECKS['connections']}
        f.call('record', *base, '--checks', f.json_file('partial.json', partial), ok=False)
        self.assertEqual(f.ledger.read_bytes(), before)
        f.call('record', *base, '--checks', f.json_file('fresh.json', CHECKS))
        h = f.read()['items'][0]['history'][-1]
        self.assertEqual(h['candidate_crop_sha256'], 'repaired-crop-0')
        self.assertFalse(f.read()['items'][0]['pending_fix'])

    def test_allowed_difference_cannot_bypass_requirement_checks(self):
        policy = {'id': 'texture', 'box_xyxy': [0, 0, 100, 100],
                  'reason': 'Texture may vary.', 'allowed_changes': ['texture'],
                  'invariants': ['labels', 'connections']}
        f = Fixture(self.root, requirements=REQUIREMENTS, policies=[policy])
        f.call('begin', '--id', 'coverage_01')
        row = dict(f.batch_rows()[0], verdict='allowed_difference', policy_id='texture')
        f.batch([row], ok=False)
        row['checks'] = dict(CHECKS, labels={'verdict': 'fail', 'note': 'The JAK1 glyphs are occluded.'})
        f.batch([row], ok=False)
        row['checks'] = CHECKS
        f.batch([row])
        self.assertEqual(f.read()['items'][0]['state'], 'allowed_difference')

    def test_batch_unknown_id_wrong_evidence_and_missing_checks_are_atomic(self):
        f = Fixture(self.root, count=2, requirements=REQUIREMENTS)
        good = f.batch_rows()
        good[0]['checks'] = CHECKS
        bad_id = copy.deepcopy(good)
        bad_id[1]['id'] = 'not_in_ledger'
        bad_evidence = copy.deepcopy(good)
        bad_evidence[1]['evidence'] = good[0]['evidence']
        bad_checks = copy.deepcopy(good)
        bad_checks[0]['checks'].pop('labels')
        before = f.ledger.read_bytes()
        for rows in (bad_id, bad_evidence, bad_checks):
            f.batch(rows, ok=False)
            self.assertEqual(f.ledger.read_bytes(), before)
        f.batch(good)
        self.assertTrue(all(i['state'] == 'pass' for i in f.read()['items']))
        self.assertEqual([len(i['history']) for i in f.read()['items']], [1, 1])

    def test_batch_requires_independent_explicit_observations(self):
        f = Fixture(self.root, count=2)
        valid = f.batch_rows()
        missing = copy.deepcopy(valid)
        missing[1].pop('note')
        generic = copy.deepcopy(valid)
        generic[1]['note'] = 'Pass.'
        repeated = copy.deepcopy(valid)
        repeated[1]['note'] = valid[0]['note']
        defaults = {'defaults': {'verdict': 'pass', 'note': 'All fine.'}, 'observations': valid}
        before = f.ledger.read_bytes()
        for rows in (missing, generic, repeated, defaults, [valid[0], valid[0]]):
            f.batch(rows, ok=False)
            self.assertEqual(f.ledger.read_bytes(), before)

    def equivalent_rectangle_rows(self):
        """Two channel nominations of one anonymous rectangular region."""
        req = {'outline': 'The rectangle has four connected outline edges.'}
        f = Fixture(self.root, count=2, requirements=req)
        j = f.read()
        second_id = j['items'][1]['id']
        second = copy.deepcopy(j['items'][0])
        second.update(id=second_id, channel='another-channel', evidence=str(f.pairs[1]))
        f.pairs[1].write_bytes(f.pairs[0].read_bytes())  # Distinct paths; identical registered pair bytes.
        j['items'][1] = second
        f.ledger.write_text(json.dumps(j))
        rows = f.batch_rows()
        for row in rows:
            row['note'] = 'The rectangle outline joins at all four corners without an open seam.'
            row['checks'] = {'outline': {'verdict': 'pass', 'note': 'Each horizontal edge meets both vertical edges.'}}
        return f, rows

    def test_batch_same_box_same_evidence_allows_reused_concrete_observation(self):
        f, rows = self.equivalent_rectangle_rows()
        self.assertNotEqual(rows[0]['evidence'], rows[1]['evidence'])
        f.batch(rows)
        j = f.read()
        self.assertTrue(all(i['state'] == 'pass' for i in j['items']))
        self.assertEqual(j['items'][0]['history'][-1]['note'], j['items'][1]['history'][-1]['note'])
        self.assertEqual(j['items'][0]['history'][-1]['evidence_sha256'], j['items'][1]['history'][-1]['evidence_sha256'])

    def test_batch_reused_observation_different_box_rejected_atomically(self):
        f, rows = self.equivalent_rectangle_rows()
        j = f.read(); j['items'][1]['box_xyxy'] = [25, 0, 75, 50]
        f.ledger.write_text(json.dumps(j)); before = f.ledger.read_bytes()
        result = f.batch(rows, ok=False)
        self.assertIn('Repeated batch notes', result.stderr)
        self.assertEqual(f.ledger.read_bytes(), before)

    def test_batch_reused_observation_different_requirements_rejected_atomically(self):
        f, rows = self.equivalent_rectangle_rows()
        j = f.read()
        j['items'][1]['requirements']['outline'] = 'The rectangle has four connected edges and a straight upper edge.'
        f.ledger.write_text(json.dumps(j)); before = f.ledger.read_bytes()
        result = f.batch(rows, ok=False)
        self.assertIn('Repeated batch notes', result.stderr)
        self.assertEqual(f.ledger.read_bytes(), before)

    def test_batch_reused_observation_different_crop_or_pair_hash_rejected_atomically(self):
        f, rows = self.equivalent_rectangle_rows()
        baseline = f.read()
        pair_bytes = f.pairs[1].read_bytes()
        for key in ('source_crop_sha256', 'candidate_crop_sha256', 'scan_evidence_sha256'):
            j = copy.deepcopy(baseline)
            f.pairs[1].write_bytes(pair_bytes)
            if key == 'scan_evidence_sha256':
                f.pairs[1].write_bytes(pair_bytes + b'different pair encoding')
                j['items'][1][key] = digest(f.pairs[1])
            else:
                j['items'][1][key] = 'different-registered-crop-hash'
            f.ledger.write_text(json.dumps(j)); before = f.ledger.read_bytes()
            with self.subTest(hash=key):
                result = f.batch(rows, ok=False)
                self.assertIn('Repeated batch notes', result.stderr)
                self.assertEqual(f.ledger.read_bytes(), before)

    def test_batch_reused_observation_different_decisions_rejected_atomically(self):
        f, rows = self.equivalent_rectangle_rows()
        j = f.read()
        j['policies'] = [{'id': name, 'box_xyxy': [0, 0, 100, 100], 'reason': 'User permits fill texture variation.',
                          'allowed_changes': ['fill texture'], 'invariants': ['closed outline']} for name in ('fill-a', 'fill-b')]
        f.ledger.write_text(json.dumps(j)); before = f.ledger.read_bytes()
        for key in ('checks', 'verdict', 'policy_id'):
            changed = copy.deepcopy(rows)
            if key == 'checks':
                changed[1]['checks']['outline']['note'] = 'All rectangle corners meet; the upper edge is horizontal.'
            else:
                for row in changed:
                    row.update(verdict='allowed_difference', policy_id='fill-a')
                changed[1][key] = 'pass' if key == 'verdict' else 'fill-b'
            with self.subTest(field=key):
                result = f.batch(changed, ok=False)
                self.assertIn('Repeated batch notes', result.stderr)
                self.assertEqual(f.ledger.read_bytes(), before)

    def test_batch_active_pending_and_stop_on_problem(self):
        f = Fixture(self.root, count=2)
        rows = f.batch_rows()
        f.call('begin', '--id', 'coverage_01')
        before = f.ledger.read_bytes()
        f.batch([rows[1]], ok=False)
        self.assertEqual(f.ledger.read_bytes(), before)
        stops_early = copy.deepcopy(rows)
        stops_early[0]['verdict'] = 'fix_required'
        f.batch(stops_early, ok=False)
        self.assertEqual(f.ledger.read_bytes(), before)
        rows[1]['verdict'] = 'fix_required'
        rows[1]['note'] = 'The right arrow crosses the first letter of the label.'
        f.batch(rows)
        self.assertEqual(f.read()['active'], 'coverage_02')
        self.assertTrue(f.read()['items'][1]['pending_fix'])
        before = f.ledger.read_bytes()
        f.batch([rows[0]], ok=False)
        self.assertEqual(f.ledger.read_bytes(), before)
        f.write_scan('repaired')
        f.call('rebase', *f.scan_args)
        f.batch([f.batch_rows()[0]], ok=False)
        repaired = f.batch_rows()[1]
        f.batch([repaired])
        self.assertIsNone(f.read()['active'])

    def test_queue_and_status_prioritize_pending_without_writing(self):
        f = Fixture(self.root, count=2, requirements=REQUIREMENTS)
        f.record('uncertain')
        before = f.ledger.read_bytes()
        queue = json.loads(f.call('queue', '--limit', '1').stdout)
        status = json.loads(f.call('status').stdout)
        self.assertEqual(queue['remaining'], 2)
        self.assertEqual(len(queue['items']), 1)
        self.assertEqual(queue['items'][0]['requirements'], REQUIREMENTS)
        self.assertEqual(queue['items'][0]['evidence'], str(f.pairs[0]))
        self.assertEqual(status['active'], 'coverage_01')
        self.assertEqual(status['next']['id'], 'coverage_01')
        self.assertEqual(f.ledger.read_bytes(), before)

    def test_record_rejects_input_change_and_rebase_rejects_stale_scan(self):
        f = Fixture(self.root)
        f.call('begin', '--id', 'coverage_01')
        before = f.ledger.read_bytes()
        f.candidate.write_bytes(b'changed after scan')
        f.batch(f.batch_rows(), ok=False)
        f.call('rebase', *f.scan_args, ok=False)
        self.assertEqual(f.ledger.read_bytes(), before)

    def test_fresh_discovery_requires_new_checks_and_new_nomination(self):
        f = Fixture(self.root, requirements=REQUIREMENTS)
        checks = f.json_file('checks.json', CHECKS)
        f.record(extra=['--checks', checks])
        f.call('start-discovery', *f.scan_args)
        f.batch([dict(f.batch_rows()[0], checks=CHECKS)], ok=False)
        f.write_scan()
        scan = json.loads(f.scan.read_text())
        new_pair = self.root / 'new_pair.png'
        new_pair.write_bytes(b'new nomination evidence')
        scan['proposals'].append(dict(scan['coverage'][0], id='new_arrow',
                                      box_xyxy=[10, 10, 40, 40], evidence=str(new_pair)))
        f.scan.write_text(json.dumps(scan))
        f.call('rebase', *f.scan_args)
        self.assertEqual([i['state'] for i in f.read()['items']], ['open', 'open'])
        f.batch(f.batch_rows(), ok=False)
        rows = f.batch_rows()
        for row in rows:
            row['checks'] = CHECKS
        f.batch(rows)
        f.call('finish-discovery', *f.scan_args, '--note', 'Fresh coverage and the newly nominated arrow were both observed.')
        f.independent_pass()
        f.call('check', *f.scan_args)
        # Altering the final scan remains a failure, even with complete observations.
        scan['run_id'] = 'altered-after-review'
        f.scan.write_text(json.dumps(scan))
        f.call('check', *f.scan_args, ok=False)

    def test_fixed_id_coordinates_and_same_box_requirements_survive_rebase(self):
        f = Fixture(self.root, requirements=REQUIREMENTS)
        f.record(extra=['--checks', f.json_file('checks.json', CHECKS)])
        f.write_scan()
        scan = json.loads(f.scan.read_text())
        carried = dict(scan['coverage'][0], id='carry_01', ledger_id='coverage_01')
        scan['source_regions'] = [carried]
        scan['coverage'][0].pop('requirements')
        carried['box_xyxy'] = [0, 0, 49, 50]
        f.scan.write_text(json.dumps(scan))
        before = f.ledger.read_bytes()
        f.call('rebase', *f.scan_args, ok=False)
        self.assertEqual(f.ledger.read_bytes(), before)
        carried['box_xyxy'] = [0, 0, 50, 50]
        critical = dict(carried, id='new_label_check', requirements={'labels': REQUIREMENTS['labels']})
        critical.pop('ledger_id')
        scan['source_regions'].append(critical)
        f.scan.write_text(json.dumps(scan))
        f.call('rebase', *f.scan_args)
        self.assertEqual(f.read()['items'][0]['requirements'], REQUIREMENTS)
        self.assertEqual(f.read()['items'][1]['id'], 'new_label_check')
        self.assertEqual(f.read()['items'][1]['state'], 'open')

    def test_external_finding_reopens_pass_and_blocks_advancing(self):
        f = Fixture(self.root, count=2)
        f.batch(f.batch_rows())
        evidence = self.root / 'hidden-underlay.png'
        evidence.write_bytes(b'actual new hidden-underlay evidence fixture')
        f.call('flag', '--id', 'coverage_01', '--note', 'Hidden underlay reveals a cut across the solid body.', '--evidence', evidence)
        issue = f.read()['items'][0]
        self.assertTrue(issue['pending_fix'])
        self.assertEqual(issue['state'], 'fix_required')
        f.call('begin', '--id', 'coverage_02', ok=False)
        f.call('start-discovery', *f.scan_args, ok=False)
        f.call('check', *f.scan_args, ok=False)
        f.write_scan(revision='repaired')
        f.call('rebase', *f.scan_args)
        f.batch(f.batch_rows())
        self.assertFalse(f.read()['items'][0]['pending_fix'])


    def test_abort_discovery_after_late_edit_requires_new_full_sweep(self):
        f = Fixture(self.root)
        f.record()
        f.call('start-discovery', *f.scan_args)
        bound = f.read()['artifact_sha256']
        evidence = f.pairs[0]
        f.artifact.write_text('<svg><path id="repaired"/></svg>')
        f.write_scan('repaired')
        f.call('rebase', *f.scan_args, ok=False)
        f.call('abort-discovery', '--id', 'coverage_01', '--note',
               'A hidden underlay exposed repeated circular shading; geometry was already revised.',
               '--evidence', evidence)
        j = f.read()
        self.assertEqual(j['artifact_sha256'], bound)
        self.assertNotEqual(j['artifact_sha256'], digest(f.artifact))
        self.assertEqual(j['items'][0]['state'], 'fix_required')
        self.assertTrue(j['items'][0]['pending_fix'])
        self.assertEqual(j['discovery']['state'], 'required')
        f.call('check', *f.scan_args, ok=False)
        f.call('rebase', *f.scan_args)
        f.record()
        f.call('finish-discovery', *f.scan_args, '--note', 'Attempt to skip new sweep.', ok=False)
        f.call('start-discovery', *f.scan_args)
        f.write_scan('repaired')
        f.call('rebase', *f.scan_args)
        f.record()
        f.call('finish-discovery', *f.scan_args, '--note', 'All reopened evidence observed again.')
        f.independent_pass()
        f.call('check', *f.scan_args)

    def test_abort_discovery_validates_state_and_evidence_without_mutating(self):
        f = Fixture(self.root)
        args = ['--id', 'coverage_01', '--note', 'Contour review requires a new local repair.', '--evidence', f.pairs[0]]
        prior = f.ledger.read_bytes()
        f.call('abort-discovery', *args, ok=False)
        self.assertEqual(prior, f.ledger.read_bytes())
        f.record()
        f.call('start-discovery', *f.scan_args)
        prior = f.ledger.read_bytes()
        f.call('abort-discovery', '--id', 'coverage_01', '--note', 'Missing proof.', ok=False)
        f.call('abort-discovery', '--id', 'unknown', '--note', 'Wrong issue identifier.', '--evidence', f.pairs[0], ok=False)
        f.call('abort-discovery', '--id', 'coverage_01', '--note', 'pass', '--evidence', f.pairs[0], ok=False)
        self.assertEqual(prior, f.ledger.read_bytes())

if __name__ == '__main__':
    unittest.main(verbosity=2)
