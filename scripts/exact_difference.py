#!/usr/bin/env python3
"""Lossless difference inventory for normalized 8-bit RGBA, plus a white-background view.
No threshold, blur, minimum component area, resize, warp or top-N in this inventory.
Heuristic ranking is separate. Guarantee concerns these finite normalized pixel arrays,
not semantic errors, original vector geometry, HDR, or every human-visible discrepancy.
"""
import argparse, hashlib, io, json, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageCms, ImageOps


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def normalize(path):
    with Image.open(path) as original:
        if getattr(original, 'n_frames', 1) != 1:
            raise ValueError('Only a single still image is supported.')
        info = {'original_mode': original.mode, 'original_size': list(original.size),
                'exif_orientation': original.getexif().get(274, 1),
                'icc_present': bool(original.info.get('icc_profile')),
                'gamma_tag': original.info.get('gamma')}
        im = ImageOps.exif_transpose(original)
        alpha = im.convert('RGBA').getchannel('A')
        profile = original.info.get('icc_profile')
        if profile:
            # Convert tagged color, preserve alpha. Unsupported profiles fail visibly.
            color = im if im.mode in ('RGB', 'CMYK', 'LAB', 'L') else im.convert('RGB')
            rgb = ImageCms.profileToProfile(color, ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                                            ImageCms.createProfile('sRGB'), outputMode='RGB')
            rgba = rgb.convert('RGBA'); rgba.putalpha(alpha)
            info['color_handling'] = 'embedded ICC converted to sRGB; alpha preserved'
        else:
            rgba = im.convert('RGBA')
            info['color_handling'] = 'untagged decoded values treated as sRGB; gamma tag not applied'
        a = np.array(rgba, dtype=np.uint8)
    info['normalized_sha256'] = hashlib.sha256(a.tobytes()).hexdigest()
    return a, info


def white(a):
    # Explicit integer round-to-nearest, same contract on every run.
    v = a.astype(np.uint32); alpha = v[..., 3:4]
    return ((v[..., :3]*alpha + 255*(255-alpha) + 127)//255).astype(np.uint8)


def measure(a, b, tile_size=96):
    if a.shape != b.shape:
        raise ValueError('Input canvases differ; no implicit resize, registration or warp.')
    if a.dtype != np.uint8 or a.ndim != 3 or a.shape[2] != 4 or b.dtype != np.uint8:
        raise ValueError('Expected normalized uint8 RGBA arrays.')
    if tile_size < 8:
        raise ValueError('tile_size must be at least 8')
    delta = np.abs(a.astype(np.int16)-b.astype(np.int16)).astype(np.uint8)
    visible = np.abs(white(a).astype(np.int16)-white(b).astype(np.int16)).astype(np.uint8)
    raw_magnitude = delta.max(axis=2); visible_magnitude = visible.max(axis=2)
    raw = raw_magnitude > 0; h, w = raw.shape
    tiles = []
    # Fixed spatial IDs retain identity between scans. Only zero-difference tiles are omitted.
    for y in range(0, h, tile_size):
        for x in range(0, w, tile_size):
            x1, y1 = min(w, x+tile_size), min(h, y+tile_size)
            patch = raw[y:y1, x:x1]; n = int(patch.sum())
            if n == 0:
                continue
            yy, xx = np.nonzero(patch); vm = visible_magnitude[y:y1, x:x1]
            tiles.append({'id': f'exact_t{tile_size}_x{x:05d}_y{y:05d}',
                          'channel': 'exact_difference', 'box_xyxy': [x, y, x1, y1],
                          'difference_bbox_xyxy': [x+int(xx.min()), y+int(yy.min()), x+int(xx.max())+1, y+int(yy.max())+1],
                          'changed_pixels': n, 'visible_changed_pixels': int((vm > 0).sum()),
                          'max_rgba_delta': int(raw_magnitude[y:y1, x:x1].max()),
                          'visible_delta_mean': round(float(vm.mean()), 6),
                          'status': 'needs_review'})
    covered = np.zeros((h, w), dtype=bool)
    for t in tiles:
        x,y,x1,y1 = t['box_xyxy']; covered[y:y1,x:x1] = True
    omitted = int((raw & ~covered).sum())
    if omitted or sum(t['changed_pixels'] for t in tiles) != int(raw.sum()):
        raise AssertionError('Difference coverage is incomplete or double counted')
    return {'rgba_delta': delta, 'raw_mask': raw, 'raw_magnitude': raw_magnitude,
            'visible_magnitude': visible_magnitude, 'tiles': tiles,
            'proof': {'normalized_changed_pixels': int(raw.sum()),
                      'white_composite_changed_pixels': int((visible_magnitude > 0).sum()),
                      'assigned_changed_pixels': sum(t['changed_pixels'] for t in tiles),
                      'unassigned_changed_pixels': omitted, 'tile_count': len(tiles)}}


def export(reference, candidate, out, tile_size=96, previous=None):
    started = time.perf_counter(); out = Path(out)
    for source in (reference,candidate,previous):
        if source and Path(source).resolve().is_relative_to(out.resolve()):
            raise ValueError('Output directory must not contain an input or previous manifest; use a fresh scan directory.')
    out.mkdir(parents=True, exist_ok=True)
    a, an = normalize(reference); b, bn = normalize(candidate)
    result = measure(a,b,tile_size); h,w = a.shape[:2]
    paths = {}
    def save(name, array):
        p = out/(name+'.png'); Image.fromarray(array).save(p)
        paths[name] = {'path': p.name, 'sha256': sha(p)}
    save('source_rgba', a); save('candidate_rgba', b)
    save('source', white(a)); save('candidate', white(b))
    save('rgba_delta', result['rgba_delta'])
    save('mask', result['raw_mask'].astype(np.uint8)*255)
    save('visible_magnitude', result['visible_magnitude'])
    save('visible_mask', (result['visible_magnitude']>0).astype(np.uint8)*255)
    # A display derivative, deliberately not used for detection or coverage accounting.
    heat = np.zeros((h,w,4), dtype=np.uint8); heat[...,0]=238; heat[...,1]=43; heat[...,2]=88
    heat[...,3] = np.where(result['raw_mask'], 170, 0); save('overlay', heat)
    transition = None
    if previous:
        prev_path = Path(previous); prev = json.loads(prev_path.read_text())
        if prev['reference_sha256'] != sha(reference) or prev['tile_size'] != tile_size or prev['canvas'] != [w,h]:
            raise ValueError('Previous scan reference, canvas and tile size must match.')
        for key in ('candidate_rgba','mask'):
            p = prev_path.parent/prev['files'][key]['path']
            if sha(p) != prev['files'][key]['sha256']:
                raise ValueError('Previous scan evidence changed: '+key)
        old = np.array(Image.open(prev_path.parent/prev['files']['candidate_rgba']['path']).convert('RGBA'))
        oldmask = np.array(Image.open(prev_path.parent/prev['files']['mask']['path'])) > 0
        changed_candidate = np.any(old != b, axis=2); raw = result['raw_mask']
        flags = {'new_difference': raw & ~oldmask, 'resolved_to_equal': oldmask & ~raw,
                 'remaining_difference': oldmask & raw, 'candidate_changed': changed_candidate}
        for name, mask in flags.items(): save(name, mask.astype(np.uint8)*255)
        # Include disappeared tiles: a repair still needs review even when it reaches equality.
        union = {t['id']:t for t in prev['tiles']}
        union.update({t['id']:t for t in result['tiles']})
        reopened = []
        for t in union.values():
            x,y,x1,y1=t['box_xyxy']
            if changed_candidate[y:y1,x:x1].any(): reopened.append(t['id'])
        transition = {'previous_manifest_sha256': sha(previous),
                      'pixel_counts': {k:int(v.sum()) for k,v in flags.items()},
                      'reopen_tile_ids': sorted(reopened),
                      'note': 'resolved means normalized equality only; remaining is not a verdict; changed candidates require renewed observation'}
    manifest = {'schema':1, 'canvas':[w,h], 'tile_size':tile_size,
                'reference_sha256':sha(reference), 'candidate_sha256':sha(candidate),
                'normalization':{'reference':an,'candidate':bn,
                  'contract':'EXIF-oriented, ICC-to-sRGB if tagged, otherwise decoded values assumed sRGB; 8-bit RGBA. No resizing/warp. Exact means any channel differs by >=1. White composite has separate visible mask. No guarantee outside this finite grid.'},
                'files':paths, 'proof':result['proof'], 'tiles':result['tiles'], 'transition':transition,
                'elapsed_seconds':round(time.perf_counter()-started,4),
                'limit':'All unequal normalized pixels are marked and assigned; these are NOT all semantic errors, and not all are defects. Tolerances, ranking and authorized substitutions never erase this inventory.'}
    (out/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    template=Path(__file__).resolve().parent.parent/'assets/difference-viewer/index.html'
    if template.exists():
        data=json.dumps(manifest,ensure_ascii=False).replace('<','\\u003c')
        (out/'index.html').write_text(template.read_text().replace('__SCAN_DATA__',data))
    return manifest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference',type=Path,required=True);ap.add_argument('--candidate',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True);ap.add_argument('--tile-size',type=int,default=96)
    ap.add_argument('--previous',type=Path,help='Prior exact manifest for iteration masks and reopened IDs')
    args=ap.parse_args()
    try:
        m=export(args.reference,args.candidate,args.out,args.tile_size,args.previous)
        print(json.dumps({'proof':m['proof'],'elapsed_seconds':m['elapsed_seconds'],'out':str(args.out)},ensure_ascii=False))
    except (ValueError,OSError) as e:ap.exit(2,str(e)+'\n')
if __name__=='__main__':main()
