#!/usr/bin/env python3
"""Portable synthetic regressions for proposal signals, not semantic correctness.

Uses the same Pillow/numpy/OpenCV dependencies as scan_differences.py.
All CLI output is generated under a temporary directory.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image
from scan_differences import CHANNELS, compute_maps


class ScanTests(unittest.TestCase):
    def canvas(self):
        return np.full((112, 160, 3), 255, dtype=np.uint8)

    def test_identical_and_dimension_mismatch(self):
        a = self.canvas()
        cv2.circle(a, (60, 50), 20, (30, 110, 170), -1)
        self.assertTrue(all(np.max(v) == 0 for v in compute_maps(a, a).values()))
        with self.assertRaises(ValueError):
            compute_maps(a, a[:-1])

    def test_visible_change_channels(self):
        # Each case isolates an observed failure category and measures a local ROI.
        a = self.canvas()
        cv2.line(a, (20, 50), (140, 50), (25, 25, 25), 7)
        b = self.canvas()
        cv2.line(b, (20, 50), (140, 50), (25, 25, 25), 2)
        self.assertGreater(compute_maps(a, b)['ink_weight'][40:60, 20:140].mean(), 20)

        a = self.canvas()
        cv2.line(a, (30, 60), (130, 60), (20, 20, 20), 3)
        cv2.line(a, (130, 45), (130, 75), (20, 20, 20), 3)
        b = self.canvas()
        cv2.line(b, (30, 60), (130, 60), (20, 20, 20), 3)
        self.assertGreater(compute_maps(a, b)['missing_edges'][40:80, 120:140].mean(), 10)
        self.assertGreater(compute_maps(b, a)['added_edges'][40:80, 120:140].mean(), 10)

        a[:] = (175, 90, 95)
        b = a.copy()
        b[35:75, 60:100] = 255
        maps = compute_maps(a, b)
        self.assertGreater(maps['fill_gaps'][40:70, 65:95].mean(), 50)
        self.assertGreater(maps['added_brightness'][40:70, 65:95].mean(), 50)
        self.assertGreater(maps['fine_color'][40:70, 65:95].mean(), 50)

        a[:] = (175, 100, 105)
        b = a.copy()
        a[25:85, 30:130] = (205, 130, 135)
        self.assertGreater(compute_maps(a, b)['broad_tone'][35:75, 40:120].mean(), 15)

        # A shifted black glyph is a colour/edge difference but not a coloured-fill gap.
        a = self.canvas()
        b = self.canvas()
        cv2.putText(a, 'T', (40, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        cv2.putText(b, 'T', (45, 80), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
        self.assertEqual(float(compute_maps(a, b)['fill_gaps'].max()), 0)

    def test_cli_coverage_and_fixed_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            a = self.canvas()
            a[10:95, 20:145] = (110, 190, 170)
            b = a.copy()
            b[35:70, 60:95] = 255
            Image.fromarray(a).save(p/'source.png')
            Image.fromarray(b).save(p/'candidate.png')
            regions = {'canvas': [160, 112], 'regions': [
                {'id': 'custom_joint', 'ledger_id': 'stable_joint',
                 'box_xyxy': [50, 25, 110, 85],
                 'requirements': {'shape': 'The colored joint has no white hole.',
                                  'labels': 'The terminal label remains unobstructed.'}}]}
            (p/'regions.json').write_text(json.dumps(regions))
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name('scan_differences.py')),
                '--reference', str(p/'source.png'), '--candidate', str(p/'candidate.png'),
                '--out', str(p/'scan'), '--regions', str(p/'regions.json'),
                '--tile-size', '64', '--per-channel', '2',
            ], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            s = json.loads((p/'scan/scan.json').read_text())
            self.assertEqual(set(s['channels']), set(CHANNELS))
            self.assertTrue(s['run_id'] and s['started_at_ns'] > 0)
            coverage = np.zeros(a.shape[:2], dtype=np.uint8)
            for item in s['coverage']:
                x, y, x1, y1 = item['box_xyxy']
                coverage[y:y1, x:x1] += 1
            self.assertTrue(np.all(coverage == 1))
            seed = s['source_regions'][0]
            self.assertEqual(seed['id'], 'custom_joint')
            self.assertNotEqual(seed['source_crop_sha256'], seed['candidate_crop_sha256'])
            with Image.open(seed['evidence']) as im:
                self.assertEqual(im.size, (120, 85))
            self.assertTrue(any(c['channel'] == 'fill_gaps' for c in s['components']))
            self.assertEqual(seed['requirements'], regions['regions'][0]['requirements'])
            self.assertEqual(seed['ledger_id'], 'stable_joint')
            self.assertEqual(s['output_mode'], 'full')

            lean_result = subprocess.run([
                sys.executable, str(Path(__file__).with_name('scan_differences.py')),
                '--reference', str(p/'source.png'), '--candidate', str(p/'candidate.png'),
                '--out', str(p/'lean'), '--regions', str(p/'regions.json'),
                '--tile-size', '64', '--per-channel', '2', '--lean',
            ], capture_output=True, text=True)
            self.assertEqual(lean_result.returncode, 0, lean_result.stderr)
            lean = json.loads((p/'lean/scan.json').read_text())
            self.assertEqual(lean['output_mode'], 'lean')
            for key in ('channels', 'components', 'parameters', 'canvas',
                        'reference_sha256', 'candidate_sha256'):
                self.assertEqual(lean[key], s[key], key)
            for key in ('proposals', 'coverage', 'source_regions', 'exhaustive_regions'):
                self.assertEqual(len(lean[key]), len(s[key]), key)
                for lean_item, full_item in zip(lean[key], s[key]):
                    self.assertEqual({k: v for k, v in lean_item.items() if k != 'evidence'},
                                     {k: v for k, v in full_item.items() if k != 'evidence'})
                    lean_pair, full_pair = Path(lean_item['evidence']), Path(full_item['evidence'])
                    self.assertEqual(lean_pair.read_bytes(), full_pair.read_bytes())
                    self.assertEqual(hashlib.sha256(lean_pair.read_bytes()).hexdigest(),
                                     lean_item['scan_evidence_sha256'])
                    self.assertEqual([path.name for path in lean_pair.parent.iterdir()], ['pair.png'])
                    self.assertEqual(len(list(full_pair.parent.glob('*.png'))), 7)
            self.assertEqual(len(list((p/'lean').rglob('*.png'))),
                             sum(len(lean[k]) for k in ('proposals', 'coverage', 'source_regions', 'exhaustive_regions')) +
                             len(list((p/'lean/exact').glob('*.png'))))
            self.assertFalse((p/'lean/index.html').exists())
            self.assertTrue((p/'lean/exact/index.html').exists())
            self.assertEqual(lean['exact']['proof']['unassigned_changed_pixels'], 0)
            self.assertEqual(lean['exact']['proof'], s['exact']['proof'])
            self.assertEqual(lean['exact']['proof']['assigned_changed_pixels'], 35*35)
            self.assertTrue((p/'scan/index.html').exists())
            self.assertEqual(len(list((p/'scan').glob('*_native.png'))), len(CHANNELS))


if __name__ == '__main__':
    unittest.main(verbosity=2)
