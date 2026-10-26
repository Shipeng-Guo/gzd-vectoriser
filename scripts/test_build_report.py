#!/usr/bin/env python3
"""Portable standard-library regression tests for the offline report builder.

Uses the adjacent builder and bundled generated-geometry example. These tests
validate packaging and refusal behavior; they do not claim visual acceptance.
All output is confined to automatically removed temporary directories.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('build_report.py')
EXAMPLE = SCRIPT.parent.parent / 'assets' / 'comparison-report' / 'example'


class BuildReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='vector-report-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        shutil.copytree(EXAMPLE, self.inputs)
        self.manifest_path = self.inputs / 'manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
        self.output = self.root / 'report'

    def build(self, *, draft=False, succeeds=True):
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8',
        )
        command = [sys.executable, str(SCRIPT), '--manifest', str(self.manifest_path),
                   '--out', str(self.output)]
        if draft:
            command.append('--draft')
        # Run away from the manifest directory: input paths must still resolve.
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, succeeds,
                         msg=result.stdout + result.stderr)
        return result

    def data(self):
        html = (self.output / 'index.html').read_text(encoding='utf-8')
        match = re.search(r'<script id="report-data" type="application/json">(.*?)</script>',
                          html, re.S)
        self.assertIsNotNone(match)
        return html, json.loads(match.group(1))

    def test_unbound_release_refused(self):
        result = self.build(succeeds=False)
        self.assertIn('--draft', result.stderr)
        self.assertFalse(self.output.exists())

    def test_explicit_draft_succeeds_with_visible_unaccepted_status(self):
        result = self.build(draft=True)
        self.assertFalse(json.loads(result.stdout)['complete'])
        html, data = self.data()
        self.assertFalse(data['review']['complete'])
        self.assertEqual(data['review']['mode'], 'draft')
        self.assertIn('Visual acceptance is incomplete', html)
        self.assertTrue((self.output / data['files']['source']).is_file())

    def test_raster_dimensions_must_match_canvas(self):
        # Same aspect ratio passes SVG ratio check but must fail raster alignment.
        self.manifest['canvas'] = {'width': 1600, 'height': 1000}
        result = self.build(draft=True, succeeds=False)
        self.assertIn('pixel dimensions do not match canvas', result.stderr)

    def test_region_coordinates_must_be_inside_canvas(self):
        self.manifest['regions'][0]['box_xyxy'] = [0, 0, 801, 500]
        result = self.build(draft=True, succeeds=False)
        self.assertIn('box must be within the canvas', result.stderr)

    def test_script_break_text_is_safely_embedded(self):
        payload = '</script><script>window.INJECTED=1</script> & <img onerror=alert(1)>'
        self.manifest['title'] = payload
        self.manifest['regions'][0]['note'] = payload
        self.build(draft=True)
        html, data = self.data()
        self.assertEqual(data['title'], payload)
        self.assertEqual(data['regions'][0]['note'], payload)
        self.assertNotIn(payload, html)
        self.assertIn('\\u003c/script\\u003e', html)
        self.assertEqual(html.count('</script>'), 2)

    def test_previous_render_is_optional(self):
        self.manifest.pop('before_render')
        self.build(draft=True)
        _, data = self.data()
        self.assertNotIn('before_render', data['files'])
        self.assertFalse((self.output / 'media' / 'before.png').exists())

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / 'keep.txt'
        sentinel.write_text('preserve this file', encoding='utf-8')
        result = self.build(draft=True, succeeds=False)
        self.assertIn('Output already exists', result.stderr)
        self.assertEqual(sentinel.read_text(encoding='utf-8'), 'preserve this file')
        self.assertFalse((self.output / 'index.html').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
