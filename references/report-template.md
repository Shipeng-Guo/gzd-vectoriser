# Offline comparison report template

Use `scripts/build_report.py` for every vector delivery report. The template lives in `assets/comparison-report/`; its example uses generated geometry, not a user's artwork. It produces an offline, movable directory with one full-canvas comparison and linked local comparisons. Each comparison can switch its left side between the source and the previous delivered render. The right side uses the final SVG itself. Image coordinates and issue IDs remain fixed; local views crop the same full-size resources rather than duplicating them.

## Build

```sh
python scripts/build_report.py --manifest /absolute/path/report.json --out /absolute/path/new-report
```

Build the delivery report once, after the drawing and review loops finish; use the upstream scan evidence during drawing instead of rebuilding the report on every iteration. Manifest paths resolve relative to the manifest file. The output must be a new directory. `index.html`, `media/` and `audit/` must move together. No network, external scripts or external fonts are required. Template source is embedded in the generated HTML. The example can be built with `--draft`; draft mode visibly states that visual acceptance is incomplete.

Formal output requires `ledger` and `scan`. The builder binds the report source, rendered final and SVG to their recorded hashes, verifies reported region IDs/verdicts and crop bounds against the ledger, then invokes the installed `review_loop.py check`. It does **not** set any review state. A missing ledger, stale final discovery sweep, unresolved region, changed file or failed gate prevents a formal build. Since v1.2.0 the same gate also requires current independent review and explicit disposition of all persistent known findings. Report writing that finds another confirmed defect must feed it back before formal publication; use a new revision for frozen experiments. A passing check confirms records and file consistency, not semantic perfection. The audit copies are frozen records; re-running the review gate also requires the original scan evidence paths.

Accepted independent packets, reports, source/candidate images and any bound structural `views` are copied into `audit/independent-review/`. Missing or changed structural screenshots prevent formal packaging just like changed primary evidence.

## Manifest, version 1

The full JSON Schema is `assets/comparison-report/manifest.schema.json`. Minimal example:

```json
{
  "version": 1,
  "title": "Diagram reconstruction",
  "summary": "What changed and what remains approximate.",
  "canvas": {"width": 800, "height": 600},
  "source": "source.png",
  "final_svg": "final.svg",
  "final_render": "final.png",
  "before_render": "previous.png",
  "ledger": "review/ledger.json",
  "scan": "review/final-scan/scan.json",
  "regions": [{
    "id": "R01", "title": "Connection restored",
    "box_xyxy": [100, 100, 220, 240],
    "verdict": "pass",
    "summary": "Restored the connecting stroke.",
    "note": "Inspected source, final and overlay; neighboring objects remain separate."
  }],
  "steps": [{"title": "Build structure", "detail": "Describe the actual operation and visible evidence.", "image": "process/structure.png", "caption": "Separate base and foreground."}],
  "allowed_changes": [],
  "limitations": ["Typeface is approximate."],
  "assets_zip": "assets.zip"
}
```

- `canvas`: exact raster pixel dimensions; `source`, `final_render`, optional `before_render` must match. The browser reports dimension/decoding errors. `final_svg` needs a matching-aspect `viewBox`; render it to `canvas` before review.
- `regions`: stable display IDs; optional `ledger_id` binds a display region to another ledger item ID (defaults to `id`); pixel `[left, top, right, bottom]` box. A report crop may be a subset of the corresponding ledger box, never an unrelated area. Supported verdicts are `open`, `reviewing`, `fix_required`, `uncertain`, `pass`, `allowed_difference`; formal builds accept only the final two and require ledger agreement. Do not change a verdict to make a report build.
- `steps`: concise descriptions of actual operations and conclusions, optionally illustrated with raster evidence. Do not fabricate steps or claim unperformed visual review.
- `allowed_changes`: user-authorized variation and invariants. These descriptions do not create review policies or bypass the gate.
- `limitations`: approximation, unresolved issues and actual review boundaries. For drafts, name known unresolved issues explicitly. Use `--draft` until resolved or authorized.
- `assets_zip`: optional existing material archive, copied without extraction.
- No project-specific IDs, anatomy assumptions, user paths or fixed image dimensions are embedded in the template. Source/reference/evidence images are supplied per build.

## Interaction and safety

- Both ranges initialize at 50% and support keyboard arrows, Home and End. At 0% only final is visible; at 100% only reference is visible. Extremes also hide the inapplicable labels.
- Region markers are hidden by default. Marker and dropdown selection synchronize; selecting a marker opens the same region below. The local reference mode is independently selectable.
- The labelled native dropdown replaces a growing row of region buttons, supports keyboard selection, and is hidden when there are no regions. Marker selection updates the dropdown and the same local crop.
- Local crop uses the same full-size files and coordinate transform; it does not recrop into lower-resolution copies.
- Text is inserted using `textContent`; JSON escapes `<`, `>`, `&` and Unicode separators. SVG active content and nonportable external references are rejected. Raster decode failures surface in the report. The template has no analytics or external requests.
- All images load eagerly, including offscreen process evidence. `window.reportReady` resolves to `{status, pending, errors}` after initial decoding and raster dimension checks; `status` is `ready` or `error`. Each decode has a 30-second bound. The live `window.reportState` and `<html data-report-state>` also track reference switches; wait until the state is no longer `loading`, then require `ready`. Decode/missing-file/dimension errors remain visible in the page and in `errors`.
- Run the reusable check below before delivery. It checks desktop/narrow layouts, 0/50/100 positions (including keyboard endpoints), independent source/previous switches, all dropdown and marker selections, local/marker coordinate transforms, eager decoding, and local resource links. It writes `check.json`, `desktop.png`, and `narrow.png`; failure exits nonzero. Marker events are dispatched directly because intentional overlaps can cover their click targets. This smoke check does **not** assess semantic correctness, visual fidelity, or editor behavior; the visual loop remains required upstream.

```sh
NODE_PATH=/path/to/node_modules node scripts/check_report.mjs /absolute/path/new-report/index.html --browser /path/to/chrome --out /absolute/path/report-qa
```

Use the available Node and Chrome/Chromium executables; omit `NODE_PATH` if `playwright` (or `playwright-core`) already resolves. The checker uses no project-specific paths and does not download browsers. Read the JSON summary and two screenshots rather than writing another Playwright harness or reading the checker implementation for routine use.

## Example and changes

For a portable autoplay image requested for another webpage, use [GIF export](comparison-gif.md). It reuses the registered source/final renders (or before/final renders), produces a looping wipe with a shared palette, and supplies an HTML embed example. This is an optional companion to the interactive report; it does not replace manual slider control or change review acceptance.

`assets/comparison-report/example/manifest.json` is deliberately unbound and must be built with `--draft`. The geometry demonstrates a background, a separate foreground, a repaired connector and independently editable labels. It is not evidence of real image reconstruction.

Changes to this template should retain generic coordinates, stable IDs, mobile behavior and refusal to imply acceptance without review. Keep project-specific prose and imagery in the manifest and output directory.

Run the portable builder regressions from the skill root with `python scripts/test_build_report.py`; these standard-library tests use only the bundled geometry example and temporary files, and do not replace browser or visual review.

For changes to image readiness or the browser checker, run `python scripts/test_check_report.py --node /path/to/node --browser /path/to/chrome --out /absolute/path/new-test-directory` with the same optional `NODE_PATH`. It retains generated-geometry fixtures for offscreen images, omitted optional views, missing/corrupt images and missing local links. Expected failures must resolve with a diagnostic rather than hanging; this also is not visual acceptance.
