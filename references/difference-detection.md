# Difference Detection Interface

Read for the first scan; see [review-loop.md](review-loop.md) for loop state. Requires Pillow, numpy, and opencv-python. Run commands from the skill directory, using task-specific input and output paths.

## Coordinates and Outputs

Actually render the SVG at the source canvas dimensions, preserving scale, cropping, and position. Detection rejects mismatched dimensions and does not automatically register or distort the candidate. Preserve the source image, previous delivery, current SVG, and actual render. The review render must correspond to the actual presentation of the delivered artifact. If renderers produce noticeable text or geometry differences, first align the presentation used for review and reporting, then repeat affected checks; a pass from another renderer is not a substitute.

```sh
python scripts/scan_differences.py --reference source.png --candidate rendered.png \
  --out scan-r01 --regions regions.json --exact-tile-size 96 --lean
```

Omit `--regions` when no additional critical regions are needed. Use a fresh directory for every pass. `--lean` still computes all seven channels, connected candidates, coverage blocks, and the complete pixel difference record, retaining each region's native-resolution `pair.png`, hashes, and the exhaustive difference viewer. It omits only presentation heatmaps, overlays, wipe frames, and the legacy overview. Omit `--lean` when those auxiliary views are needed.

## Exhaustive Difference Record and Observation Priority

As a wipe divider crosses a coordinate, the displayed value switches from candidate C to source S; this change can be recorded as `abs(S-C)`. Sweeping every column across the image yields the same changes as a coordinate-aligned difference. The script records these display changes; it does not simulate physiological visual persistence.

`exact_difference.py` records every unequal pixel after orientation correction, ICC conversion to sRGB, and normalization to 8-bit RGBA: no blurring, threshold filtering, removal of small regions, or top-N filtering. Without an ICC profile, treat decoded values as sRGB without additionally applying gamma tags.

| Output | Purpose |
|---|---|
| `exact/mask.png` | Marks any RGBA channel difference of at least 1, including hidden colors in transparent pixels |
| `exact/visible_mask.png`, `visible_magnitude.png` | Visible differences after compositing over white; tasks with transparent backgrounds must still inspect raw alpha differences |
| `exact/manifest.json` | Hashes, all changed tiles, and assignment counts; requires `unassigned_changed_pixels == 0` |
| `scan.json.exhaustive_regions` | Imports all changed tiles into the review queue, unrestricted by seven-channel rankings |
| `exact/index.html` | All numbered tiles, enlargement, wipe comparison, and manual slow alternation; automatically included in the formal report |

The guarantee applies to these two normalized pixel arrays. Zero unassigned changed pixels means the changes have been recorded; comparison determines whether they are errors. One tile may contain several issues, and one object may span multiple tiles. Observe and modify complete objects and their neighborhoods rather than cutting objects at tile boundaries.

The seven channels independently nominate regions to prioritize attention:

| Channel | Main indication |
|---|---|
| `fine_color` | Local color differences after slight blurring |
| `missing_edges` / `added_edges` | Missing, added, or displaced edges |
| `ink_weight` | Grayscale changes in dark, low-chroma strokes that may indicate stroke-weight issues |
| `broad_tone` | Large-scale changes in tone, gradients, highlights, and shadows |
| `added_brightness` | Newly bright areas |
| `fill_gaps` | Colored source regions that become near-white in the candidate |

All thresholded connected regions remain in `components`; high-priority windows are only nominations. Observe all changed tiles, native-resolution coverage blocks, and source-derived critical regions, not just the top-N results. The seven channels composite over white by default. If the target background differs, first render both images on that background and retain separate transparency verification. Do not reduce differences by blurring the candidate or locally warping it.

## Critical Regions and Comparison Across Passes

Identify critical regions independently from the source so that missing objects cannot escape inspection merely because they are absent from the candidate tree. Coordinates use input raster pixels, not the SVG viewBox.

```json
{"canvas":[800,600],"regions":[{
  "id":"R01","name":"Component and connection","box_xyxy":[100,120,260,260],
  "requirements":{"shape":"The body is closed and the opening on the right is preserved","connection":"The short bar endpoint connects to the body's lower edge","label":"The label is fully visible"}
}]}
```

Use `requirements` only for critical regions, with content determined by the current image. Do not mechanically create the same fields for ordinary changed tiles.

```sh
python scripts/scan_differences.py --reference source.png --candidate revised.png \
  --out scan-r02 --regions fixed-regions.json \
  --previous-exact scan-r01/exact/manifest.json --exact-tile-size 96 --lean
```

`--previous-exact` additionally provides pixel maps for newly appearing differences, persistent differences, restored equality, and actual changes to the candidate. Keep the same baseline, canvas, and tile size; modified old evidence is rejected. Export fixed boxes for existing issues through the review CLI; do not drop an ID because its issue falls out of the ranking. The inner loop reopens tiles whose pixels changed; the outer discovery pass observes every changed tile again.

The agent may judge using enlarged pairs, overlays, or wipe keyframes; accurately describe the viewing method actually used in the report. Users can continue inspection with the interactive wipe.

## Similar members and relative attributes

A covered or highlighted region still needs attribute-level judgment. When a component repeats similar members, compare their **relative** hue, lightness, stroke, and orientation against the source before sharing styles. A component can have the right overall color family while losing a meaningful member difference. If observed, register that relation as a source-derived requirement and inspect it again after geometry repairs; a numeric color sample can support, but does not replace, the enlarged comparison. Never infer success from coverage alone.
