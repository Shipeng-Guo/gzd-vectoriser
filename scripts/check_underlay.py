#!/usr/bin/env python3
"""Find missing opaque fill in a hidden-foreground state.

The expected image must come from an independently constructed complete base,
not from hiding the same foreground twice. This is a bounded construction check,
not a semantic completion or general fidelity detector. Dependencies: Pillow,
NumPy, OpenCV (the same image dependencies as scan_differences.py).
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw


def load_rgba(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def on_white(rgba):
    alpha = rgba[..., 3:4].astype(np.float32) / 255
    return np.rint(rgba[..., :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)


def components(mask, min_area):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    retained = np.zeros(mask.shape, bool)
    regions = []
    for index in range(1, count):
        x, y, width, height, area = (int(v) for v in stats[index])
        if area >= min_area:
            retained |= labels == index
            regions.append({"box_xyxy": [x, y, x + width, y + height], "pixels": area})
    regions.sort(key=lambda item: (-item["pixels"], item["box_xyxy"]))
    return retained, regions


def inspect(expected, actual, *, mask=None, margin=1.0, min_area=3,
            min_alpha=240, alpha_drop=16, white_min=242, light_gain=16):
    if expected.shape != actual.shape:
        raise ValueError("Expected and actual images must have identical pixel dimensions")
    support = expected[..., 3] >= min_alpha
    if mask is not None:
        if mask.shape != support.shape:
            raise ValueError("Mask dimensions must match expected and actual images")
        support &= mask
    # Pad explicitly so fully opaque rectangular bases also get an interior.
    distance = cv2.distanceTransform(np.pad(support.astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
    interior = support & (distance > margin)
    if not interior.any():
        raise ValueError("No opaque interior remains; check the baseline, mask, or margin")
    ergb, argb = on_white(expected), on_white(actual)
    e = ergb.astype(np.int16)
    a = argb.astype(np.int16)
    missing = interior & ((expected[..., 3].astype(np.int16) - actual[..., 3]) >= alpha_drop)
    # A source white highlight is not an added hole. Coloured texture changes
    # are outside this check; use the ordinary colour/edge scanner for them.
    white = (a.min(2) >= white_min) & ((a.max(2) - a.min(2)) <= 12)
    newly_white = interior & ~missing & white & ((a.mean(2) - e.mean(2)) >= light_gain)
    channels = {}
    combined = np.zeros(interior.shape, bool)
    for name, candidate in (("alpha_loss", missing), ("new_white_fill", newly_white)):
        retained, regions = components(candidate, min_area)
        combined |= retained
        channels[name] = {"pixels": int(retained.sum()), "regions": regions}
    return {
        "status": "attention_required" if combined.any() else "no_candidates",
        "dimensions": {"width": int(actual.shape[1]), "height": int(actual.shape[0])},
        "interior_pixels": int(interior.sum()),
        "candidate_pixels": int(combined.sum()),
        "channels": channels,
    }, combined, interior


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True, type=Path, help="Independent complete base render")
    parser.add_argument("--actual", required=True, type=Path, help="Base-only render after hiding foreground")
    parser.add_argument("--mask", type=Path, help="Optional grayscale mask: white is known solid base")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--margin", type=float, default=1.0, help="Exclude this many pixels at the true base boundary")
    parser.add_argument("--min-area", type=int, default=3)
    parser.add_argument("--light-gain", type=int, default=16)
    args = parser.parse_args()
    if args.margin < 0 or args.min_area < 1 or not 1 <= args.light_gain <= 255:
        parser.error("Require margin >= 0, min-area >= 1 and light-gain in [1, 255]")
    expected, actual = load_rgba(args.expected), load_rgba(args.actual)
    mask = None
    if args.mask:
        with Image.open(args.mask) as image:
            mask = np.asarray(image.convert("L")) > 127
    try:
        report, candidates, interior = inspect(expected, actual, mask=mask,
            margin=args.margin, min_area=args.min_area, light_gain=args.light_gain)
    except ValueError as error:
        parser.error(str(error))
    args.out.mkdir(parents=True, exist_ok=True)
    report["inputs"] = {key: {"path": str(path.resolve()), "sha256": digest(path)}
                        for key, path in (("expected", args.expected), ("actual", args.actual))}
    if args.mask:
        report["inputs"]["mask"] = {"path": str(args.mask.resolve()), "sha256": digest(args.mask)}
    report["settings"] = {"margin_px": args.margin, "min_area_px": args.min_area,
                          "light_gain": args.light_gain, "min_alpha": 240,
                          "alpha_drop": 16, "white_min": 242}
    report["scope"] = [
        "Baseline completeness and intended geometry require independent visual verification.",
        "Checks only known opaque interior; translucent regions and excluded boundary pixels are not covered.",
        "No candidates does not prove smoothness, hidden geometry correctness, or final-composite fidelity.",
    ]
    (args.out / "check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    Image.fromarray(candidates.astype(np.uint8) * 255).save(args.out / "candidates.png")
    Image.fromarray(interior.astype(np.uint8) * 255).save(args.out / "checked-interior.png")
    canvas = Image.fromarray(on_white(actual))
    draw = ImageDraw.Draw(canvas)
    for channel in report["channels"].values():
        for region in channel["regions"]:
            x0, y0, x1, y1 = region["box_xyxy"]
            draw.rectangle((x0 - 2, y0 - 2, x1 + 1, y1 + 1), outline="#e02040", width=2)
    canvas.save(args.out / "marked.png")
    print(json.dumps({"status": report["status"], "candidate_pixels": report["candidate_pixels"],
                      "report": str(args.out / "check.json")}))
    return 1 if report["candidate_pixels"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
