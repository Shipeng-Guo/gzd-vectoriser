#!/usr/bin/env python3
"""Synthetic bookkeeping regression tests; these do not constitute visual review."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import independent_review as gate
from test_review_loop import Fixture


class IndependentGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = Fixture(self.root)
        self.j = self.f.read()
        self.seq = 0

    def prepare(self, phase='discovery', j=None, views=None):
        self.seq += 1
        path = gate.packet(j or self.j, phase, self.root / ('packet_' + str(self.seq)), views=views)
        report = gate.read(path.parent / 'report-template.json')
        report.update(reviewer_id='separate-reviewer-session', independence_attestation=True)
        for row in report['coverage']:
            row.update(verdict='pass', note='Synthetic distinct image observation for ' + row['id'])
            for key, check in row.get('checks', {}).items():
                check.update(verdict='pass', note='Synthetic source requirement check: ' + key)
        for row in report['resolutions']:
            row.update(verdict='fixed', note='Synthetic independent current-image recheck of ' + row['id'])
        return path, report

    def submit(self, phase='discovery'):
        path, report = self.prepare(phase)
        self.j = gate.record(self.j, path, report)
        return path

    def finding(self):
        path, report = self.prepare()
        report['findings'] = [{'title': 'Disconnected connector endpoint', 'box_xyxy': [2, 2, 20, 20],
                               'note': 'Connector endpoint stops before the source boundary.',
                               'evidence': ['source', 'candidate']}]
        self.j = gate.record(self.j, path, report)
        return self.j['independent_review']['issues'][0]['id']

    def test_new_init_requires_gate_and_explicit_maker_is_supported(self):
        self.assertTrue(self.j['independent_review']['required'])
        with self.assertRaisesRegex(ValueError, 'discovery'):
            gate.check(self.j)
        g = copy.deepcopy(self.j)
        del g['independent_review']
        gate.attach(g, 'maker-session-17')
        self.assertEqual(g['independent_review']['maker_id'], 'maker-session-17')
        with self.assertRaisesRegex(ValueError, 'cannot be replaced'):
            gate.attach(g, 'another-maker')

    def test_clean_current_complete_coverage_passes(self):
        self.submit()
        self.assertTrue(gate.check(self.j)['complete'])
        self.assertEqual(len(self.j['independent_review']['reviews'][-1]['report']['coverage']), 10)

    def test_stale_source_render_artifact_and_scope_rejected(self):
        self.submit()
        for key in ('reference', 'candidate', 'artifact'):
            path = Path(self.j[key]); old = path.read_bytes()
            path.write_bytes(old + b'change')
            with self.assertRaisesRegex(ValueError, 'changed'):
                gate.check(self.j)
            changed_binding = copy.deepcopy(self.j)
            changed_binding[key + '_sha256'] = gate.sha(path)
            with self.assertRaisesRegex(ValueError, 'stale'):
                gate.check(changed_binding)
            path.write_bytes(old)
        self.j['items'][0]['requirements'] = {'endpoint': 'The connector must meet the source boundary.'}
        with self.assertRaisesRegex(ValueError, 'stale'):
            gate.check(self.j)

    def test_missing_duplicate_and_generic_coverage_rejected_atomically(self):
        path, report = self.prepare()
        before = copy.deepcopy(self.j)
        for edit in ('missing', 'duplicate', 'generic'):
            bad = copy.deepcopy(report)
            if edit == 'missing': bad['coverage'].pop()
            if edit == 'duplicate': bad['coverage'][-1] = bad['coverage'][0]
            if edit == 'generic': bad['coverage'][0]['note'] = 'looks good'
            with self.assertRaises(ValueError):
                gate.record(self.j, path, bad)
            self.assertEqual(self.j, before)

    def test_failed_coverage_cannot_claim_empty_clean_report(self):
        path, report = self.prepare()
        report['coverage'][1]['verdict'] = 'uncertain'
        with self.assertRaisesRegex(ValueError, 'persistent findings'):
            gate.record(self.j, path, report)

    def test_new_findings_block_and_empty_later_report_cannot_erase_them(self):
        issue_id = self.finding()
        with self.assertRaisesRegex(ValueError, 'no independent resolution'):
            gate.check(self.j)
        self.submit()  # A fresh empty finding list is not a resolution.
        self.assertEqual([i['id'] for i in self.j['independent_review']['issues']], [issue_id])
        with self.assertRaisesRegex(ValueError, 'no independent resolution'):
            gate.check(self.j)

    def test_missing_recheck_resolution_rejected_atomically(self):
        self.finding()
        path, report = self.prepare('recheck')
        report['resolutions'] = []
        before = copy.deepcopy(self.j)
        with self.assertRaisesRegex(ValueError, 'Every known issue'):
            gate.record(self.j, path, report)
        self.assertEqual(self.j, before)

    def test_fixed_all_issues_needs_fresh_discovery_then_passes(self):
        self.finding()
        old_packet, old_report = self.prepare()
        self.submit('recheck')
        with self.assertRaisesRegex(ValueError, 'Fresh clean'):
            gate.check(self.j)
        with self.assertRaisesRegex(ValueError, 'stale'):
            gate.record(self.j, old_packet, old_report)
        self.submit()
        self.assertTrue(gate.check(self.j)['complete'])

    def test_new_findings_in_recheck_still_block(self):
        self.finding()
        path, report = self.prepare('recheck')
        report['findings'] = [{'title': 'Label overlaps border', 'box_xyxy': [40, 40, 50, 50],
                               'note': 'The final glyph crosses the border in the current render.',
                               'evidence': ['source', 'candidate']}]
        self.j = gate.record(self.j, path, report)
        self.assertEqual(len(self.j['independent_review']['issues']), 2)
        self.submit()
        with self.assertRaisesRegex(ValueError, 'no independent resolution'):
            gate.check(self.j)

    def test_repaired_artifact_stales_each_known_resolution(self):
        self.finding(); self.submit('recheck'); self.submit()
        self.f.artifact.write_text('<svg><path id="changed"/></svg>')
        self.j['artifact_sha256'] = gate.sha(self.f.artifact)
        self.submit()
        with self.assertRaisesRegex(ValueError, 'stale'):
            gate.check(self.j)
        self.submit('recheck'); self.submit()
        self.assertTrue(gate.check(self.j)['complete'])

    def test_packets_are_blind_and_recheck_has_no_pass_claims(self):
        self.finding(); self.submit('recheck')
        path, _ = self.prepare()
        p = gate.read(path)
        self.assertNotIn('known_issues', p)
        self.assertNotIn('history', p)
        self.assertNotIn('reviews', p)
        self.assertNotIn('maker_id', p)
        path, _ = self.prepare('recheck')
        issue = gate.read(path)['known_issues'][0]
        self.assertEqual(set(issue), {'id', 'title', 'box_xyxy', 'observations'})
        self.assertNotIn('fixed', json.dumps(issue))

    def test_wrong_identity_missing_attestation_and_unrelated_evidence_fail(self):
        path, report = self.prepare()
        for field, value in [('reviewer_id', self.j['independent_review']['maker_id']), ('independence_attestation', False)]:
            bad = copy.deepcopy(report); bad[field] = value
            with self.assertRaisesRegex(ValueError, 'distinct from the maker'):
                gate.record(self.j, path, bad)
        report['coverage'][0]['evidence'] = ['candidate']
        with self.assertRaisesRegex(ValueError, 'both current packet images'):
            gate.record(self.j, path, report)

    def test_image_mutation_invalidates_review(self):
        packet = self.submit()
        evidence = Path(gate.read(packet)['images']['candidate']['path'])
        evidence.write_bytes(b'different image')
        with self.assertRaisesRegex(ValueError, 'evidence'):
            gate.check(self.j)

    def test_allowed_difference_needs_existing_bounded_policy(self):
        self.finding()
        path, report = self.prepare('recheck')
        report['resolutions'][0].update(verdict='allowed_difference', policy_id='user-policy')
        with self.assertRaisesRegex(ValueError, 'existing policy'):
            gate.record(self.j, path, report)
        self.j['policies'] = [{'id': 'user-policy', 'box_xyxy': [0, 0, 25, 25],
                              'reason': 'User requested color simplification in this region.',
                              'allowed_changes': ['color simplification'], 'invariants': ['connections remain intact']}]
        path, report = self.prepare('recheck')
        report['resolutions'][0].update(verdict='allowed_difference', policy_id='user-policy')
        self.j = gate.record(self.j, path, report)
        self.submit()
        self.assertTrue(gate.check(self.j)['complete'])
        self.j['policies'][0]['strict_boxes'] = [[5, 5, 10, 10]]
        with self.assertRaises(ValueError): gate.check(self.j)

    def test_rejection_still_needs_current_image_evidence(self):
        self.finding()
        path, report = self.prepare('recheck')
        report['resolutions'][0].update(verdict='rejected', note='The full pair shows the apparent endpoint gap is the intended source gap.')
        self.j = gate.record(self.j, path, report)
        self.submit()
        self.assertTrue(gate.check(self.j)['complete'])

    def test_migration_retains_historical_failures_despite_later_maker_pass(self):
        self.f.record('fix_required'); self.f.record()
        legacy = self.f.read(); del legacy['independent_review']
        gate.attach(legacy, 'original-maker')
        self.assertEqual(legacy['independent_review']['issues'][0]['id'], 'local:coverage_01')
        with self.assertRaisesRegex(ValueError, 'no independent resolution'):
            gate.check(legacy)

    def test_new_local_failure_reopens_previously_resolved_issue(self):
        self.f.record('fix_required'); self.f.record()
        self.j = self.f.read(); self.submit('recheck'); self.submit()
        self.assertTrue(gate.check(self.j)['complete'])
        gate.track_local(self.j, self.j['items'][0], {'note': 'The repaired outline again has an open seam.'})
        with self.assertRaisesRegex(ValueError, 'stale'):
            gate.check(self.j)
        self.assertEqual(len(self.j['independent_review']['issues']), 1)

    def test_release_builder_refuses_legacy_missing_independent_gate(self):
        from build_report import review
        self.f.clean_discovery()
        j = self.f.read(); del j['independent_review']
        gate.save(self.f.ledger, j)
        paths = {'ledger': self.f.ledger, 'scan': self.f.scan, 'source': self.f.source,
                 'final_render': self.f.candidate, 'final_svg': self.f.artifact}
        data = {'canvas': {'width': 100, 'height': 100}, 'regions': []}
        with self.assertRaisesRegex(ValueError, 'Mandatory independent'):
            review(paths, data, False, self.root)
        self.assertFalse(review(paths, data, True, self.root)['complete'])

    def test_resolution_cannot_disagree_with_the_independent_report(self):
        self.finding(); self.submit('recheck'); self.submit()
        self.j['independent_review']['issues'][0]['resolutions'][-1]['verdict'] = 'rejected'
        with self.assertRaisesRegex(ValueError, 'disagrees'):
            gate.check(self.j)

    def test_release_freezes_current_recheck_and_discovery_evidence(self):
        from build_report import copy_independent_evidence
        self.finding(); self.submit('recheck'); self.submit()
        destination = self.root / 'portable-report'
        (destination / 'audit').mkdir(parents=True)
        link = copy_independent_evidence(self.j, destination, gate.context(self.j)[0])
        frozen = gate.read(destination / link)
        self.assertEqual([r['phase'] for r in frozen['reviews']], ['recheck', 'discovery'])
        self.assertEqual(len(frozen['known_issues']), 1)
        for row in frozen['reviews']:
            folder = (destination / link).parent
            self.assertEqual(gate.sha(folder / row['packet']), row['packet_sha256'])
            self.assertEqual(gate.fingerprint(gate.read(folder / row['report'])), row['report_content_sha256'])
            for filename in row['images'].values():
                self.assertTrue((folder / filename).is_file())
        with self.assertRaisesRegex(ValueError, 'changed while packaging'):
            copy_independent_evidence(self.j, destination, {})

    def test_packet_cannot_smuggle_maker_pass_narrative(self):
        path, report = self.prepare()
        packet = gate.read(path)
        packet['maker_notes'] = 'Everything was approved earlier.'
        gate.save(path, packet)
        report['packet_sha256'] = gate.sha(path)
        with self.assertRaisesRegex(ValueError, 'narrative'):
            gate.record(self.j, path, report)

    def structural_view(self):
        # Anonymous fixture: rectangle plus interior line, with no project geometry.
        from PIL import Image, ImageDraw
        path = self.root / 'structural-observation.png'
        image = Image.new('RGBA', (48, 36), (255, 255, 255, 0))
        draw = ImageDraw.Draw(image)
        draw.rectangle((5, 5, 42, 30), fill=(60, 150, 120, 255), outline=(0, 0, 0, 255), width=2)
        draw.line((10, 18, 36, 18), fill=(0, 0, 0, 255), width=2)
        image.save(path)
        return {'id': 'isolated-base', 'path': str(path), 'artifact_sha256': self.j['artifact_sha256'],
                'description': 'Foreground hidden; isolated rectangular base and its interior line are visible.'}

    def test_structural_views_recheck_and_release_freeze_current_png(self):
        from build_report import copy_independent_evidence
        self.finding()
        view = self.structural_view()
        path, report = self.prepare('recheck', views=[view])
        packet = gate.read(path)
        copied = packet['views'][view['id']]
        self.assertEqual(copied['artifact_sha256'], self.j['artifact_sha256'])
        self.assertEqual(copied['sha256'], gate.sha(view['path']))
        self.assertNotEqual(copied['path'], view['path'])
        report['resolutions'][0]['evidence'].append('view:' + view['id'])
        self.j = gate.record(self.j, path, report)
        self.submit()  # Ordinary whole-image discovery remains compatible.
        self.assertTrue(gate.check(self.j)['complete'])
        destination = self.root / 'views-report'
        (destination / 'audit').mkdir(parents=True)
        link = copy_independent_evidence(self.j, destination, gate.context(self.j)[0])
        frozen = gate.read(destination / link)
        recheck = next(r for r in frozen['reviews'] if r['phase'] == 'recheck')
        frozen_view = (destination / link).parent / recheck['views'][view['id']]
        self.assertEqual(gate.sha(frozen_view), copied['sha256'])
        self.assertTrue(frozen_view.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(set(report), {'packet_sha256', 'reviewer_id', 'independence_attestation', 'coverage', 'findings', 'resolutions'})

    def test_structural_view_input_rejects_stale_binding_and_claim_metadata(self):
        view = self.structural_view()
        invalid = [dict(view, artifact_sha256='0' * 64), dict(view, id='../escape'),
                   dict(view, passed=True), dict(view, description='pass')]
        for n, bad in enumerate(invalid):
            target = self.root / ('bad-view-' + str(n))
            with self.subTest(case=n), self.assertRaises(ValueError):
                gate.packet(self.j, 'discovery', target, views=[bad])
            self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError, 'unique'):
            gate.packet(self.j, 'discovery', self.root / 'duplicates', views=[view, view])

    def test_structural_views_reject_text_svg_and_broken_png(self):
        view = self.structural_view()
        for n, content in enumerate([b'<svg/>', b'visual approval text', b'\x89PNG\r\n\x1a\nnot-a-decodable-image']):
            path = self.root / ('not-an-image-' + str(n) + '.png')
            path.write_bytes(content)
            with self.subTest(case=n), self.assertRaisesRegex(ValueError, 'PNG'):
                gate.packet(self.j, 'discovery', self.root / ('invalid-packet-' + str(n)), views=[dict(view, path=str(path))])

    def test_structural_views_mutation_or_missing_image_blocks_record_atomically(self):
        path, report = self.prepare(views=[self.structural_view()])
        image = Path(next(iter(gate.read(path)['views'].values()))['path'])
        original = image.read_bytes()
        before = copy.deepcopy(self.j)
        for missing in (False, True):
            if missing: image.unlink()
            else: image.write_bytes(b'mutated evidence')
            with self.subTest(missing=missing), self.assertRaises((ValueError, OSError)):
                gate.record(self.j, path, report)
            self.assertEqual(self.j, before)
            image.write_bytes(original)

    def test_structural_views_mutation_or_missing_image_blocks_check_and_release(self):
        from build_report import copy_independent_evidence
        self.finding()
        path, report = self.prepare('recheck', views=[self.structural_view()])
        report['resolutions'][0]['evidence'].append('view:isolated-base')
        self.j = gate.record(self.j, path, report)
        self.submit()
        image = Path(next(iter(gate.read(path)['views'].values()))['path'])
        original = image.read_bytes()
        for missing in (False, True):
            if missing: image.unlink()
            else: image.write_bytes(b'mutated evidence')
            with self.subTest(missing=missing), self.assertRaises((ValueError, OSError)):
                gate.check(self.j)
            destination = self.root / ('rejected-release-' + str(missing))
            (destination / 'audit').mkdir(parents=True)
            with self.assertRaises((ValueError, OSError)):
                copy_independent_evidence(self.j, destination)
            image.write_bytes(original)

    def test_structural_evidence_references_must_exist_and_retain_source_pair(self):
        path, report = self.prepare(views=[self.structural_view()])
        for refs in (['view:isolated-base'], ['source', 'candidate', 'view:unknown'],
                     ['source', 'candidate', 'view:isolated-base', 'view:isolated-base']):
            bad = copy.deepcopy(report)
            bad['coverage'][0]['evidence'] = refs
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                gate.record(self.j, path, bad)
        report['coverage'][0]['evidence'].append('view:isolated-base')
        self.j = gate.record(self.j, path, report)
        self.assertTrue(gate.check(self.j)['complete'])

    def test_structural_packet_metadata_cannot_rebind_an_old_artifact(self):
        path, report = self.prepare(views=[self.structural_view()])
        packet = gate.read(path)
        packet['views']['isolated-base']['artifact_sha256'] = '0' * 64
        gate.save(path, packet)
        report['packet_sha256'] = gate.sha(path)
        with self.assertRaisesRegex(ValueError, 'binding is stale'):
            gate.record(self.j, path, report)

    def test_views_cli_paths_resolve_relative_to_manifest_without_autoapproval(self):
        view = self.structural_view()
        manifest = self.root / 'views.json'
        gate.save(manifest, [dict(view, path=Path(view['path']).name)])
        target = self.root / 'cli-packet'
        before = self.f.ledger.read_bytes()
        result = subprocess.run([sys.executable, str(Path(gate.__file__)), 'packet', '--ledger', str(self.f.ledger),
                                 '--phase', 'discovery', '--output', str(target), '--views', str(manifest)],
                                cwd=self.root.parent, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.f.ledger.read_bytes(), before)
        template = gate.read(target / 'report-template.json')
        self.assertFalse(template['independence_attestation'])
        self.assertEqual(template['reviewer_id'], '')
        self.assertTrue(all(c['verdict'] == '' and c['note'] == '' for c in template['coverage']))
        copied = gate.read(target / 'packet.json')['views']['isolated-base']
        Path(view['path']).unlink()  # Packet's frozen image is independent of the producer location.
        self.assertEqual(gate.sha(copied['path']), copied['sha256'])
        gate.validate_packet(gate.read(target / 'packet.json'), self.j)
        legacy = gate.packet(self.j, 'discovery', self.root / 'without-views', views=[])
        self.assertNotIn('views', gate.read(legacy))

    def test_default_review_loop_check_requires_new_gate(self):
        self.f.clean_discovery()
        self.assertIn('independent_review', json.loads(self.f.call('check', *self.f.scan_args).stdout))
        j = self.f.read(); j['independent_review']['reviews'] = []
        gate.save(self.f.ledger, j)
        result = self.f.call('check', *self.f.scan_args, ok=False)
        self.assertIn('independent whole-image', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
