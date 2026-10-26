# SVG to native editable PPTX

Read only when PPTX is needed. Reuse paths, text, hierarchy, and drawing order from the same SVG and map them to native PowerPoint objects. When the user needs to edit individual shapes or text, do not substitute a full-slide SVG image or several SVG image tiles for native objects.

## Approach and execution

1. **Define the output contract.** The task determines slide count, aspect ratio, fonts, and editable scope. Retain the SVG. Group components according to what the user wants to move together; arrow shafts and arrowheads should belong to the same unit. Photos or authorized display bitmaps may be separate image objects, but do not claim that their internal details are editable point by point.
2. **Parse and convert.** Read directly from the current SVG rather than maintaining a separate set of PowerPoint coordinates that can drift. Unify canvas units, flatten ancestor transforms, and preserve drawing order. Measure the actual fonts before emitting text boxes, emit curves as cubic Beziers, and selection groups as native `p:grpSp` elements.
3. **Validate the actual PPTX.** Check counts of native shapes, text, and images, as well as group membership. Render the PPTX and compare it with the SVG in the same coordinates, checking font baselines, wrapping, rotation, line widths, gradients, and occlusion. Verify ungrouping, movement, and text editing on representative groups. File structure checks are not operation tests in the target editor.
4. **Deliver.** Save the SVG and PPTX separately. Include an actual PPTX preview and the editable scope in the report. If arrows are freeform paths, explain that their endpoints need adjustment after components move. Promise automatic following only when actual connectors were created. Report renders must match the final slide content.

When generating local PPTX files in Codex, use the currently installed Presentations skill to locate the runtime, perform the authoring mark step, and complete final validation. Do not hardcode its installed version or user paths in this skill. Other agent environments may substitute a backend, but must still satisfy the native-object and actual-rendering acceptance requirements above. If a runtime library is missing, identify it; do not fall back to a full-slide image and call it editable.

## Reusable conversion tool

`scripts/svg_to_pptx.mjs` parses SVG in a browser, emits generic scene data, and generates a draft with `@oai/artifact-tool`. `pptx_native_groups.py` restores nested native groups, line caps and joins, and fonts while preserving leaf objects' world coordinates. These tools produce candidates only; they do not declare visual acceptance.

Dependencies: Node, Playwright, an available Chromium executable, `@oai/artifact-tool`, and the Python standard library. Locate available runtimes first; `RUNTIME_NODE_MODULES` can point to an existing package directory.

```sh
node scripts/svg_to_pptx.mjs drawing.svg --out new-private-build \
  --browser /path/to/chrome --python /path/to/python --width 1280
```

- `--width` is slide width in CSS pixels, defaulting to 1280. Height follows the SVG viewBox aspect ratio; the tool does not stretch it to 16:9. If 16:9 is needed, first create an SVG canvas with that aspect ratio.
- Outputs are `candidate.pptx`, `scene.json`, `structure.json`, and `source.png`. The last file is a browser preview of the SVG and cannot serve as evidence that the PPTX has been rendered.
- `scene.json` preserves object IDs, world-space geometry, text styles, and group paths. Apply conversion corrections to the appropriate source object or converter, retaining the original SVG.
- Unsupported elements or styles raise an error identifying the object. They are not silently omitted or automatically rasterized. After fixing the issue, retry in a new output directory.

### Supported normalized SVG subset

Simple `text`, `g`, `rect` (including rounded corners), `circle/ellipse`, `line/polyline/polygon`, and explicit absolute `M/L/C/Z` paths; translation, rotation, and positive uniform scaling; solid colors and axis-aligned, full-span linear gradients; fonts, font weights, italics, line caps, and line joins. Elements without IDs receive conversion IDs without modifying the source file.

First normalize arcs and relative paths to absolute cubic curves, and expand markers and similar features into actual geometry. This tool does not currently handle clipping, masks, filters, opacity, dashed strokes, rich text, skew, reflection, nonuniform transforms, nested SVGs, images, or other gradients. Expand them faithfully, extend the backend, or use an authorized mixed approach as needed. Retain the original input and compare renders before and after normalization; do not sacrifice appearance or text editability to fit the tool.

### Details to retain during acceptance

- The text-style API uses `typeface`. Do not mask font fallback with an ineffective `fontFamily` property. Check text baselines in the target renderer even after measuring.
- For leaf objects already flattened into slide coordinates, set group `off = chOff` and `ext = chExt` to avoid applying translation or scaling twice. Preserve object order and remove unnecessary group locks.
- The current tool's single-slide output, simple text, and limited SVG support are explicit implementation boundaries. Do not extrapolate them into lossless conversion of arbitrary SVGs.
- Use new filenames for both the final file and validation receipt. Keep the receipt inside the working directory but outside the final output directory. Pass runtime package paths to the finalizer's subprocess.
- When only the export backend changes, do not repeat the source SVG's full review loop; check differences introduced by conversion. If the SVG changes, invalidate the corresponding old evidence and recheck.

Regression: `python scripts/test_svg_to_pptx.py --node /path/to/node --browser /path/to/chrome --out new-test-dir`. Tests check coordinates, curves, native text, group identity, and rejection of unsupported features. Also inspect the actual render for appearance.
