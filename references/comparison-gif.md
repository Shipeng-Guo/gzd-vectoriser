# Automatic wipe-comparison GIF

Use when the user needs to embed a source/vector or before/after wipe comparison in another webpage. Requires Python and Pillow. Reuse existing raster images in the same coordinate system; render SVGs to PNG at the source dimensions using the current project's renderer first. The script does not operate Illustrator, redraw the artwork, or perform vector acceptance.

```sh
python scripts/make_comparison_gif.py \
  --reference source.png --candidate final-render.png \
  --out new-animation --width 960
```

- Inputs must have identical dimensions and coordinates. Mismatched dimensions are rejected; the tool does not automatically align or stretch one image. EXIF orientation is applied first. Transparent inputs are composited onto a white background.
- Omit `--width` to retain the original dimensions. For local comparisons, use `--crop LEFT TOP RIGHT BOTTOM`; the same source-pixel box is applied to both images before proportional resizing.
- By default, the wipe travels back and forth automatically at 20 fps, taking about 3.2 seconds in each direction and pausing for about 1.1 seconds at each endpoint, for a cycle of about 8.5 seconds. Adjust with `--fps`, `--sweep-seconds`, and `--hold-seconds`. GIF timing has 10 ms precision; actual frame counts and durations are recorded in the metadata.
- The default English labels are `Source` and `Final SVG`. For Chinese labels, supply the translated text with `--reference-label` and `--candidate-label`, plus `--font /path/to/chinese-font.ttf`, or use `--no-labels`. The current environment supplies the font; no fixed user path is required.
- To compare against a previous version, use its render as `--reference` and change its label to `Before`; the candidate remains the current final render.

The new output directory contains `comparison.gif`, a four-phase comparison decoded from the actual GIF as `check.png`, parameters and input hashes in `animation.json`, and an offline-playable `index.html` with `<img>` embed code. After uploading the GIF, reference it as an ordinary image; no JavaScript is required.

## Implementation details to retain

The entire animation shares a 256-color palette. The two static images are quantized only once before composing frames, reducing repeated computation and avoiding palette flicker. A fixed palette can still map pure white to near-white, so pure-white pixels are explicitly restored. The script handles cosine easing, endpoint holds, and GIF frame disposal that retains the previous frame.

After export, decode every frame and verify dimensions, duration, infinite looping, and frame-sampling completeness. Actually inspect `check.png` and play the result, checking wipe direction, misalignment, ghosting, labels, and colors. The quantized GIF is a presentation preview; continue to assess vector quality using the original SVG render. Do not treat GIF color differences as new SVG defects.

To move actual SVG elements and demonstrate grouping and complete underlays, use [component explosion and reassembly](group-motion.md) instead. Wiping between static images does not verify that group members move together.
