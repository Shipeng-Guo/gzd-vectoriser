#!/usr/bin/env python3
"""Export a looping wipe GIF from two registered raster images.

Requires Pillow. SVGs must already be rendered at the reference size.
Writes comparison.gif, check.png, animation.json and index.html in a NEW directory.
"""
import argparse
import hashlib
import html
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps, ImageSequence

WHITE, TEAL, BORDER, INK = (255, 255, 255), (17, 124, 131), (205, 222, 219), (24, 61, 66)


def read_raster(path):
    with Image.open(path) as original:
        if getattr(original, 'n_frames', 1) != 1:
            raise ValueError('Inputs must be static raster images, not animations.')
        rgba = ImageOps.exif_transpose(original).convert('RGBA')
    return Image.alpha_composite(Image.new('RGBA', rgba.size, WHITE + (255,)), rgba).convert('RGB')


def quantize(image, palette):
    result = image.quantize(palette=palette, dither=Image.Dither.NONE)
    # Pillow fixed-palette lookup uses coarse RGB bins. Reserving a white entry
    # alone does not guarantee exact white, so restore these pixels explicitly.
    r, g, b = image.split()
    mask = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v == 255 else 0)
    result.paste(252, mask=mask)
    return result


def make_label(text, font_path, width):
    if not text.isascii() and font_path is None:
        raise ValueError('Non-ASCII labels require --font with a suitable local font, or --no-labels.')
    pad = max(4, round(width * .0102))
    max_width = max(1, (width - 4 * pad) // 2)
    for size in range(max(10, round(width * 25 / 1280)), 7, -1):
        if font_path:
            font = ImageFont.truetype(str(font_path), size)
        else:
            try:
                font = ImageFont.truetype('DejaVuSans.ttf', size)
            except OSError:
                try:
                    font = ImageFont.load_default(size=size)
                except TypeError:
                    font = ImageFont.load_default()
        box = font.getbbox(text)
        w, h = box[2] - box[0] + 2 * pad, box[3] - box[1] + 2 * pad
        if w <= max_width:
            break
    else:
        raise ValueError('Labels are too long for this width; shorten them or use --no-labels.')
    tag = Image.new('RGB', (w, h), WHITE)
    draw = ImageDraw.Draw(tag)
    draw.rounded_rectangle((0, 0, w-1, h-1), radius=max(2, pad//2), fill=WHITE, outline=BORDER)
    draw.text((pad-box[0], pad-box[1]), text, font=font, fill=INK)
    return tag


def create_comparison(reference, candidate, out, *, width=None, crop=None,
                      fps=20, sweep_seconds=3.2, hold_seconds=1.1,
                      reference_label='Source', candidate_label='Final SVG',
                      font=None, labels=True):
    reference, candidate, out = map(lambda p: Path(p).resolve(), (reference, candidate, out))
    if out.exists():
        raise ValueError('Output directory already exists; choose a new directory.')
    if not (math.isfinite(fps) and 1 <= fps <= 50):
        raise ValueError('fps must be between 1 and 50.')
    if not (math.isfinite(sweep_seconds) and sweep_seconds > 0):
        raise ValueError('sweep-seconds must be positive.')
    if not (math.isfinite(hold_seconds) and hold_seconds >= 0):
        raise ValueError('hold-seconds must be nonnegative.')
    source, final = read_raster(reference), read_raster(candidate)
    if source.size != final.size:
        raise ValueError('Inputs must have identical registered dimensions; no automatic alignment or stretching.')
    input_size = source.size
    if crop is not None:
        left, top, right, bottom = crop
        if not (0 <= left < right <= source.width and 0 <= top < bottom <= source.height):
            raise ValueError('Crop must be a nonempty box inside the input canvas.')
        source, final = source.crop(crop), final.crop(crop)
    if width is None:
        width = source.width
    if not isinstance(width, int) or width <= 0:
        raise ValueError('width must be a positive integer.')
    height = max(1, round(source.height * width / source.width))
    if max(width, height) > 65535:
        raise ValueError('Output dimensions exceed the GIF format limit.')
    if source.size != (width, height):
        source = source.resize((width, height), Image.Resampling.LANCZOS)
        final = final.resize((width, height), Image.Resampling.LANCZOS)
    tags = [make_label(t, font, width) for t in (reference_label, candidate_label)] if labels else []
    margin = max(4, round(width * 20 / 1280))
    if any(tag.height + margin > height for tag in tags):
        raise ValueError('Canvas is too short for labels; use --no-labels.')

    # Quantize the registered stills once, then compose indexed frames. This
    # avoids re-quantizing 128 full RGB frames and keeps colors temporally stable.
    a, b = source.copy(), final.copy()
    a.thumbnail((1024, 1024)); b.thumbnail((1024, 1024))
    sample = Image.new('RGB', (a.width+b.width, max(a.height, b.height)+32), WHITE)
    sample.paste(a, (0, 0)); sample.paste(b, (a.width, 0))
    palette = sample.quantize(colors=252, method=Image.Quantize.MEDIANCUT)
    # Sparse diagrams can return fewer than 252 colors. Pad before appending so
    # reserved indices 252..255 retain their meaning even for two-color inputs.
    base_palette = palette.getpalette()[:252*3]
    base_palette += [0] * (252*3-len(base_palette))
    palette.putpalette(base_palette + list(WHITE+TEAL+BORDER+INK))
    source_p, final_p = quantize(source, palette), quantize(final, palette)
    tags = [quantize(tag, palette) for tag in tags]
    frame_ms = max(20, round(1000 / fps / 10) * 10)
    hold_ms = max(frame_ms, round(hold_seconds * 1000 / 10) * 10)
    steps = max(2, round(sweep_seconds * 1000 / frame_ms))
    ratios = [1.0]
    ratios += [(1 + math.cos(math.pi*i/steps))/2 for i in range(1, steps+1)]
    ratios += [(1 - math.cos(math.pi*i/steps))/2 for i in range(1, steps)]
    frames, durations = [], []
    line_width = max(1, round(width * 4 / 1280))
    for i, ratio in enumerate(ratios):
        x = round(width * ratio)
        frame = final_p.copy()
        if x:
            frame.paste(source_p.crop((0, 0, x, height)), (0, 0))
        if 0 < x < width:
            ImageDraw.Draw(frame).rectangle(
                (x-line_width//2, 0, x+(line_width-1)//2, height-1), fill=253)
        if tags:
            if x:
                frame.paste(tags[0], (margin, margin))
            if x < width:
                frame.paste(tags[1], (width-margin-tags[1].width, margin))
        frames.append(frame)
        durations.append(hold_ms if i in (0, steps) else frame_ms)

    out.mkdir(parents=True, exist_ok=False)
    gif_path = out/'comparison.gif'
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=durations,
                   loop=0, disposal=1, optimize=False)
    # Decode the encoded GIF. Disposal/cropping errors would be invisible if QA
    # only inspected our pre-encoding frames.
    times = [0, hold_ms+(steps//2-1)*frame_ms,
             hold_ms+(steps-1)*frame_ms, 2*hold_ms+(steps+steps//2-2)*frame_ms]
    thumb_w = min(480, width)
    thumb_h = max(1, round(height*thumb_w/width))
    contact = Image.new('RGB', (thumb_w*2, thumb_h*2), WHITE)
    elapsed, captured = 0, set()
    with Image.open(gif_path) as saved:
        loop = saved.info.get('loop')
        for frame in ImageSequence.Iterator(saved):
            rgb = frame.convert('RGB')
            rgb.load()
            duration = frame.info.get('duration', 0)
            for i, timestamp in enumerate(times):
                if i not in captured and elapsed <= timestamp < elapsed + duration:
                    rgb_thumb = rgb.resize((thumb_w, thumb_h), Image.Resampling.LANCZOS)
                    contact.paste(rgb_thumb, ((i%2)*thumb_w, (i//2)*thumb_h))
                    captured.add(i)
            elapsed += duration
        frame_count = saved.n_frames
        if saved.size != (width, height) or loop != 0 or elapsed != sum(durations) or len(captured) != 4:
            raise RuntimeError('Encoded GIF validation failed; inspect retained output.')
    contact.save(out/'check.png')
    metadata = {
        'reference': str(reference), 'candidate': str(candidate),
        'reference_sha256': hashlib.sha256(reference.read_bytes()).hexdigest(),
        'candidate_sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(),
        'input_canvas': list(input_size), 'crop_xyxy': list(crop) if crop else None,
        'width': width, 'height': height, 'generated_frames': len(frames),
        'encoded_frames': frame_count, 'duration_ms': elapsed, 'loop': loop,
        'requested_fps': fps, 'effective_moving_fps': 1000/frame_ms,
        'moving_frame_ms': frame_ms, 'endpoint_hold_ms': hold_ms,
        'bytes': gif_path.stat().st_size, 'labels': [reference_label, candidate_label] if labels else [],
        'palette': 'shared 256 colors; exact-white protection; alpha composited onto white',
        'decoded_check': 'passed', 'visual_acceptance': 'Inspect check.png and play the GIF.'
    }
    (out/'animation.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+'\n')
    title = html.escape(reference_label + ' / ' + candidate_label)
    markup = '<img src="comparison.gif" alt="' + html.escape(reference_label+' / '+candidate_label, quote=True) + '" style="max-width:100%;height:auto;">'
    (out/'index.html').write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>'+title+'</title><style>body{max-width:1100px;margin:32px auto;padding:0 20px;font:17px/1.6 system-ui;color:#183d42}'
        'img{display:block;width:100%;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>'+title+'</h1>'+
        markup+'<p><a href="comparison.gif" download>Download GIF</a> · '+str(width)+' × '+str(height)+' · '+str(elapsed/1000)+' s loop</p>'+
        '<pre><code>'+html.escape(markup)+'</code></pre></html>', encoding='utf-8')
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='New output directory')
    parser.add_argument('--width', type=int, help='Output width; default: native or cropped width')
    parser.add_argument('--crop', nargs=4, type=int, metavar=('LEFT', 'TOP', 'RIGHT', 'BOTTOM'))
    parser.add_argument('--fps', type=float, default=20, help='Moving FPS, 1–50; GIF timing rounds to 10 ms')
    parser.add_argument('--sweep-seconds', type=float, default=3.2)
    parser.add_argument('--hold-seconds', type=float, default=1.1)
    parser.add_argument('--reference-label', default='Source')
    parser.add_argument('--candidate-label', default='Final SVG')
    parser.add_argument('--font', type=Path, help='Local font with required glyphs; required for non-ASCII labels')
    parser.add_argument('--no-labels', action='store_true')
    args = vars(parser.parse_args())
    args['labels'] = not args.pop('no_labels')
    try:
        result = create_comparison(**args)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
