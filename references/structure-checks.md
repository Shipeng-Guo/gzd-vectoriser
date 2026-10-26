# Structural and Editing Acceptance Interface

Read when object construction or grouping needs verification. First determine members, foreground/underlay relationships, and required appearance from the source and editing intent, then inspect the candidate. Probes operate on copies without modifying input files; also inspect the generated evidence images.

## Movement and Membership

```sh
node scripts/probe_edit_unit.mjs drawing.svg --cases edit-cases.json \
  --out new-edit-evidence --browser /path/to/chrome
```

```json
[{"id":"component","delta":[20,0],
  "watch":["external-connector","background"],
  "members":["component.body","component.label","attached-symbol"]}]
```

- Determine `members` independently from the source, then check that all parts expected to move together belong to the group. Do not define expectations merely by enumerating existing group members.
- Include nearby connections or objects that should remain independent in `watch`, and check that their rendered positions do not change. Unchanged local path coordinates do not imply unchanged screen positions.
- Inspect before and after movement, the old and new positions, hidden states, and neighboring areas. No member may be missing, no unrelated object may move with the group, and no remnants may remain. Text must also be independently editable.
- Regrouping should preserve the composite appearance; also check stacking order, inherited styles, transforms, and clipping.

Requires Playwright and sharp; set `NODE_PATH` if needed. Outputs include `result.json`, screenshots, and raw pixel differences. The default pixel tolerance is 0. Reproduce and locate browser redraw noise first; `--pixel-renderer sharp` provides an independent deterministic render for verification, while retaining browser evidence. Use `--pixel-tolerance 1` only for confirmed single-level antialiasing fluctuations, without changing the main scan's difference record or accepting actual displacement.

DOM probes record membership and positional behavior. When the user specifies a target editor, additionally inspect imported structure and representative selection, movement, and text-editing behavior in that editor. Distinguish the scope actually tested in the report.

## Directional Occlusion Checks

Declare the foreground and underlay first, then hide the foreground and isolate the underlay. Moving or hiding the underlay does not substitute for this direction. This check is needed for underlay gaps invisible in the composite. Select representative objects for different construction methods; if one fails, expand checks to other objects built the same way.

In `occlusion.json`, coordinates are zero-origin SVG viewBox units, not source-image pixels. Output uses one pixel per unit and retains the same dimensions on every reload. The contract requires at least one solid region; add `clear_regions` for confirmed, genuinely transparent openings.

```json
{"version":1,"cases":[{
  "id":"overlap-01","foreground":["front"],"underlay":["base"],
  "reason":"The foreground covers a continuous solid underlay; there is a genuine opening on the right",
  "solid_regions":[{"id":"interior","polygon":[[40,40],[50,40],[50,50],[40,50]],"min_alpha":250,"forbid_white":false}],
  "clear_regions":[{"id":"opening","polygon":[[60,40],[65,40],[65,45],[60,45]],"max_alpha":5}]
}]}
```

Example coordinates only illustrate the interface; determine them independently for the current image. Solid samples exclude genuine exterior areas, holes, and translucent layers. Enable `forbid_white` only when white is explicitly inappropriate. A genuine opening is not necessarily a transparent hole; determine whether alpha checks apply from the object's construction.

```sh
python scripts/review_loop.py require-probes --ledger review.json --checks occlusion.json
node scripts/probe_occlusion.mjs drawing.svg --contract occlusion.json \
  --out new-occlusion-evidence --browser /path/to/chrome
python scripts/review_loop.py import-probe --ledger review.json --evidence new-occlusion-evidence/result.json
```

Register obligations first and import both successful and failed results. Exit code 2 means the probe found a failure. Retest after repair, rerendering, and rebase; delivery rejects failures, missing cases, changed directions or sample types, stale artifacts, and invalid evidence.

First check sample locations against the source. When a known defective candidate exists, verify that the probe detects it. If the checking contract itself is wrong, preserve the revision rationale, old contract, and failure evidence, then retest the comparison using the new contract. Do not modify the image or relax standards to accommodate an incorrect sample. Beyond the samples, inspect the entire isolated underlay's shape, color, details, and openings.

## Whole-Underlay Detection Aids

```sh
python scripts/propose_underlay_holes.py --isolated underlay-only.png --out hole-review
python scripts/check_underlay.py --expected independent-base.png \
  --actual foreground-hidden-base.png --out underlay-check
```

The first tool retains every enclosed transparent-hole candidate, including single pixels; it does not cover gaps connected to the exterior or opaque white patches. The second requires an independently confirmed, complete underlay baseline in the same coordinates and flags internal alpha loss and new white patches. By default, it excludes a one-pixel outer margin and translucent regions; use `--mask` to restrict checking to solid regions and `--margin 0` to include edges. Judge candidates through comparison, preserving genuine openings and highlights. Both tools complement whole-object observation.

## Components and File Structure

Before export, inspect each component in isolation to confirm that all members, boundaries, and colors belong to that object; proximity or matching colors do not establish membership. After export, check cropping, text, gradients, transparency, and member completeness in the standalone files. See [tools.md](tools.md) for the interface.

Return new findings through `flag` in the [review interface](review-loop.md), then rerun the relevant probes and outer discovery pass after repair. Record probe coverage, actual editor verification, and visual reproduction separately.
