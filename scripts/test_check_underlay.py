#!/usr/bin/env python3
"""Portable fixtures for the bounded opaque-underlay check."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

from check_underlay import inspect


def fixture():
    image = Image.new("RGBA", (160, 100))
    drawing = ImageDraw.Draw(image)
    drawing.rounded_rectangle((8, 8, 151, 91), radius=18, fill="#bc757b")
    drawing.rounded_rectangle((25, 18, 135, 23), radius=3, fill="white")
    return np.asarray(image).copy()


class UnderlayTests(unittest.TestCase):
    def test_unchanged_white_highlight_is_not_hole(self):
        expected = fixture()
        report, _, _ = inspect(expected, expected.copy())
        self.assertEqual(report["status"], "no_candidates")

    def test_two_types_of_missing_fill_detected_separately(self):
        expected = fixture()
        actual = expected.copy()
        actual[40:46, 35:43, 3] = 0
        actual[60:66, 105:112] = (255, 255, 255, 255)
        report, _, _ = inspect(expected, actual)
        self.assertEqual(report["status"], "attention_required")
        self.assertEqual(report["channels"]["alpha_loss"]["pixels"], 48)
        self.assertEqual(report["channels"]["new_white_fill"]["pixels"], 42)
        self.assertEqual(report["channels"]["new_white_fill"]["regions"][0]["box_xyxy"], [105, 60, 112, 66])

    def test_true_boundary_is_excluded_and_external_white_is_ignored(self):
        expected = fixture()
        actual = expected.copy()
        # The flat top border is within the default one-pixel exclusion band.
        actual[8, 30:100] = (255, 255, 255, 255)
        actual[0:4] = (255, 255, 255, 255)
        report, _, _ = inspect(expected, actual)
        self.assertEqual(report["status"], "no_candidates")
        report, _, _ = inspect(expected, actual, margin=0)
        self.assertEqual(report["channels"]["new_white_fill"]["pixels"], 70)

    def test_dimensions_and_empty_scope_fail(self):
        with self.assertRaises(ValueError):
            inspect(fixture(), fixture()[:50])
        with self.assertRaises(ValueError):
            inspect(fixture(), fixture(), mask=np.zeros((100, 160), bool))

    def test_cli_binds_evidence_and_writes_marked_regions(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            expected = fixture()
            actual = expected.copy()
            actual[40:50, 60:65] = (255, 255, 255, 255)
            Image.fromarray(expected).save(path / "base.png")
            Image.fromarray(actual).save(path / "hidden.png")
            command = [sys.executable, str(Path(__file__).with_name("check_underlay.py")),
                       "--expected", str(path / "base.png"), "--actual", str(path / "hidden.png"),
                       "--out", str(path / "check")]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            report = json.loads((path / "check/check.json").read_text())
            self.assertEqual(report["candidate_pixels"], 50)
            self.assertEqual(len(report["inputs"]["actual"]["sha256"]), 64)
            for name in ("marked.png", "candidates.png", "checked-interior.png"):
                self.assertTrue((path / "check" / name).is_file())


if __name__ == "__main__":
    unittest.main()
