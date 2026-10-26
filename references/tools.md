# General tools and runtime

Read the sections relevant to the current operation. Run commands from the skill directory, using input and output paths for the current task. Prefer existing tools; the agent chooses drawing and repair algorithms independently.

| Purpose | Tools | Dependencies |
|---|---|---|
| Complete differences, seven channels, and local comparisons | `exact_difference.py`, `scan_differences.py`, `compare_regions.py` | Python, Pillow, numpy; the seven-channel scan requires OpenCV |
| Stable IDs, inner and outer loops, and evidence acceptance | `review_loop.py`, `acceptance_probes.py` | Python standard library; the loop tool invokes the latter |
| Independent review packets, persistent findings, and acceptance of the current version | `independent_review.py` | Python; structural PNG attachments require Pillow; observation requires an independent agent |
| XML and group membership audit | `audit_svg.py` | Python standard library |
| Movement, membership, and occlusion probes | `probe_edit_unit.mjs`, `probe_occlusion.mjs` | Node, Playwright, sharp, and an available Chromium executable |
| Underlay hole candidates and baseline comparison | `propose_underlay_holes.py`, `check_underlay.py` | Python, Pillow, numpy, OpenCV |
| Fitting selected traced contours | `refit_contours.py` | Python, numpy, scipy, OpenCV |
| SVG to native single-slide PPTX | `svg_to_pptx.mjs`, `pptx_native_groups.py` | Node, Playwright, Chromium, @oai/artifact-tool; Python standard library; see the [PPTX backend](pptx.md) |
| Standalone component export | `export_edit_units.mjs` | Node, Playwright; rendering and transparent trimming require sharp |
| Offline wipe report and interaction checks | `build_report.py`, `check_report.mjs` | Python standard library; checks use Node, Playwright, Chromium |
| Exploding and reassembling actual SVG groups, revealing underlays, and GIF export | `render_group_motion.mjs`, `encode_motion_gif.py` | Node, Playwright, sharp, Chromium; Python, Pillow |
| Automatic back-and-forth wipe GIF, decoded-frame checks, and web preview | `make_comparison_gif.py` | Python, Pillow; non-ASCII labels require a suitable local font |

First locate available interpreters and dependencies. Set `NODE_PATH` explicitly if Node cannot resolve modules, and use `--browser` to specify an available local browser. Use a new output directory to retain evidence from previous rounds. Do not embed fixed machine-specific absolute paths in reusable tools.

## File structure audit

```sh
python scripts/audit_svg.py drawing.svg --manifest groups.json --output audit.json
```

The manifest is optional. When provided, use `{"groups":[{"id":"unit","members":["unit.body","unit.label"]}],"ungrouped_objects":["background"]}`. The manifest must cover every scene leaf object exactly once. Expand nested selection groups into their leaf members without also listing their parent groups. The tool checks declarations against XML; the structural contract determines editing intent.

## Standalone asset export

```sh
node scripts/export_edit_units.mjs drawing.svg --out new-assets \
  --browser /path/to/chrome --trim-transparent
```

By default, export `g[data-edit-unit="true"]`, or provide an array of IDs with `--ids ids.json`. Preserve definitions, namespaces, ancestor transforms, and nested viewports; output SVGs, transparent PNGs, and an index. `--padding` defaults to 6 coordinate units. `--trim-transparent` tightens the viewport using the actual rendered alpha while preserving the internal vector structure. Add margins for filters and shadows as needed. Inspect representative files before packaging, especially components with clipping, transforms, text, and gradients.

## Optional contour tool

Call `refit_contours.py --help` only when an identified individual traced contour needs processing. Mark new traced objects with `data-method="source-traced"` and selected paths with `data-refit="true"`; protect hand-drawn and inferred paths with `data-manual` and `data-inference`. The tool does not overwrite its input and rejects fits that violate displacement, area, or topology constraints. This is an optional method; final acceptance still follows the source image and structural contract. Do not rewrite geometry representations merely to accommodate the skill.

## Tool maintenance validation

Retain the existing synthetic geometry tests: detection and loops use `test_scan_differences.py`, `test_exact_difference.py`, `test_exact_loop.py`, and `test_review_loop.py`; structure and export use `test_probe_edit_unit.py`, `test_probe_occlusion.py`, `test_occlusion_gate.py`, `test_underlay_holes.py`, `test_check_underlay.py`, and `test_export_edit_units.py`; fitting uses `test_refit_contours.py`; reports use `test_build_report.py` and `test_check_report.py`.

Independent review and persistent-finding gates use `test_independent_review.py`, together with `test_review_loop.py` and `test_build_report.py`, covering invalidation of old approvals, omitted known findings, fresh discovery after repair, and formal packaging.

Select the relevant tests only when their code changes. Read each browser test's `--help` first to supply local Node and browser paths; other tests can run directly or through unittest in the scripts directory. Tests use anonymous geometry and failure counterexamples. Project-specific materials must not become runtime dependencies.

See [comparison-gif.md](comparison-gif.md) for the GIF export interface. Run its regression with `python scripts/test_comparison_gif.py`; check actual encoded frames for direction, endpoints, pure white and transparency background handling, timing, and cropping rather than checking only pre-encoding images.

See [group-motion.md](group-motion.md) for the component explosion and reassembly interface. Its regression is `test_group_motion.py`; use it only when an editing-structure demonstration is needed.

PPTX conversion uses `test_svg_to_pptx.py`, covering nonzero viewBox origins, nested rotation, native text, groups, and rejection of unsupported styles. It does not replace actual PPTX rendering.
