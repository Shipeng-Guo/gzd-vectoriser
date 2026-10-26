---
name: gzd-vectoriser
description: Reconstruct raster diagrams as layered, editable SVGs, with optional native editable PPTX or Illustrator output. Validate through difference detection, independent review, and regional repair; deliver component assets and a slider comparison report.
metadata:
  version: "1.4.1"
---

# GZD Vectoriser

The skill defines construction constraints, difference discovery, and the acceptance loop; the agent chooses its own drawing and repair methods. Keep the workflow general rather than relying on repair recipes for particular images.

## Construction contract

- **Build complete underlays before adding foregrounds.** Construct underlays, details, foregrounds, and text separately; underlays must remain complete when foregrounds are moved away. Preserve genuine openings and identify inferred reconstruction of hidden areas. Represent smooth contours with curves rather than preserving pixel stair steps.
- **Group by editing intent.** Layers control drawing order; selection groups contain every member that should move together. Unrelated objects remain independent, and text remains separately editable. Use stable IDs for locating and modifying objects; group names or counts do not replace editing tests.
- **Derive requirements from the source.** Align coordinates, dimensions, and transparent backgrounds. For revisions, retain the most recent delivery as a baseline. Check objects, relationships, appearance, and text, including content missing from the candidate. Check the colour, stroke width, and orientation of similar members individually; reuse must not erase their differences.
- **Define permitted changes explicitly.** Record permitted replacement regions, properties, and invariants in advance. Disclose any embedded raster content; do not substitute a full-image raster for vectors without authorisation. Actually produce the requested output in the user-specified software and record its provenance.

## Detection and repair loop

1. **Construct a first draft.** Build complete objects under the contract; inspect representative objects before reusing them.
2. **Discover differences.** Render in source coordinates using [difference detection](references/difference-detection.md). The exhaustive pixel record retains every change; seven channels help prioritise inspection. Inspect changed grid cells, coverage blocks, and critical source regions.
3. **Repair each region.** Use persistent IDs from the [review interface](references/review-loop.md), and inspect enlarged views of complete objects and their neighbourhoods. Grid cells locate differences; they do not define redraw boundaries. After each change, render again and recheck the original issue, the object's other properties, and effects on neighbours. Keep unresolved issues open; change methods or roll back when progress stalls.
4. **Check editing structure.** Use [structural checks](references/structure-checks.md) to test movement, membership, hidden foregrounds, and isolated underlays. Derive requirements from the source and editing intent, never backwards from the existing candidate.
5. **Review independently and rediscover.** Follow [independent review](references/independent-review.md) to assign a reviewer without production history. Log and repair findings, then independently recheck known issues. After regional work is complete, start a fresh whole-image scan, inspect every changed region again, and complete independent whole-image discovery on the current version. Continue the loop if new issues appear. Confirmed findings from reports, self-review, and user feedback also return to the queue.
6. **Accept and deliver.** Ensure the current SVG, render, and evidence agree; address every known issue and complete the latest outer discovery pass, independent review, and registered structural probes. Then run `review_loop.py check`, export components, and build the [slider report](references/report-template.md).

Close an issue only when content and connections are correct; shape, colour, stroke width, and occlusion meet requirements; related members move together while neighbouring objects remain independent; and the current evidence has actually been inspected. Permitted differences need a valid basis and passing invariant checks. A claim that something was changed, an earlier version's pass, or omission from a new report does not establish resolution. Keep genuinely unmet requirements explicitly unresolved.

## Run only what the task needs

| User task | Read and execute |
|---|---|
| Raster reconstruction / SVG revision | The full loop above; see [tools](references/tools.md) for dependencies and asset export |
| SVG to editable PPTX | The [PPTX backend](references/pptx.md): parse the same SVG, create native shapes, text, and groups, and inspect the actual PPTX render |
| Illustrator / AI explicitly requested | The [Illustrator backend](references/illustrator.md) |
| Slider animation / component separation and reassembly | [Comparison GIF](references/comparison-gif.md) / [group animation](references/group-motion.md) |

Read only the references needed for the current stage. When exporting an already accepted artifact, reuse its unchanged SVG and evidence; check the added format's structure and actual render, reopening the relevant loop if a problem in the source artifact is discovered. Within a pass, observations may be reused only for identical regions, requirements, and evidence. Final rediscovery cannot reuse earlier passing verdicts. Build the formal report at the end rather than rebuilding it after every repair.

When the user requests image generation first, use an available image-generation tool, check the information in the generated image, and use that image as the vectorisation baseline. Retain the original input, generated image, and generation prompt. Do not generate an additional image for ordinary vectorisation.

Deliver the SVG, an actual component asset bundle, and an illustrated process report by default; add PPTX, AI, or animation when requested. Include whole-image and necessary regional sliders in the report, add a pre-edit baseline for revision tasks, and link the difference inspection page. Record only actual operations, repairs, and verification scope, not internal chains of thought.

## Maintenance

Update only general workflow gaps and repetitive mechanical operations; keep case-specific shapes, coordinates, and lessons in the project. Validate new tools with anonymous geometry and failing counterexamples; run relevant regressions when existing code changes. Freeze the skill version during benchmark experiments.
