#!/usr/bin/env python3
"""Prepare aligned visual review evidence; never decides semantic correctness.

Requires Pillow. Inputs must already have identical canvas registration and size.
Region schema: {"canvas": [width,height], "regions": [
  {"id":"binding", "name":"...", "box_xyxy":[x0,y0,x1,y1],
   "policy":"mechanism", "checks":["..."], "tolerance":"..."}]}
Policies: mechanism, uncertain, labels, appearance, authorized_asset.
"""
import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

POLICIES = {"mechanism": 0, "uncertain": 0, "labels": 1,
            "appearance": 2, "authorized_asset": 3}
NAMES = {"mechanism": "Mechanism relationships: review required", "uncertain": "Meaning uncertain: review first",
         "labels": "Text and labels", "appearance": "Appearance: assess against the intended use",
         "authorized_asset": "Authorised display asset: pixel identity is not the acceptance criterion"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--regions", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--zoom", type=float, default=3)
    a = p.parse_args()
    if not math.isfinite(a.zoom) or not 0 < a.zoom <= 8:
        p.error("zoom must be finite and in (0, 8]")
    images = []
    for file in (a.reference, a.candidate):
        with Image.open(file) as im:
            rgba = im.convert("RGBA")
            white = Image.new("RGBA", rgba.size, "white")
            images.append(Image.alpha_composite(white, rgba).convert("RGB"))
    ref, cand = images
    spec = json.loads(a.regions.read_text())
    if ref.size != cand.size or list(ref.size) != spec.get("canvas"):
        p.error("Canvas mismatch. Render to the reference canvas; do not independently stretch or align each object.")
    regions = spec.get("regions", [])
    if not regions:
        p.error("No regions; source-based region inventory must be supplied.")
    seen = set()
    for r in regions:
        gid = r.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", gid) or gid in seen:
            p.error("Invalid or duplicate region ID")
        seen.add(gid)
        if r.get("policy") not in POLICIES:
            p.error("Unknown review policy")
        box = r.get("box_xyxy", [])
        if len(box) != 4 or any(not isinstance(v, int) for v in box):
            p.error("box_xyxy must contain four integer source-pixel coordinates")
        x0, y0, x1, y1 = box
        if not 0 <= x0 < x1 <= ref.width or not 0 <= y0 < y1 <= ref.height:
            p.error("Region lies outside the canvas or has zero area")
        if not isinstance(r.get("checks"), list) or not r["checks"]:
            p.error("Each region needs explicit source-derived checks")
        if r["policy"] == "authorized_asset" and not r.get("tolerance"):
            p.error("Authorized assets need the scope of the user's permitted variation")

    a.out.mkdir(parents=True, exist_ok=True)
    records = []
    cards = []
    for r in regions:
        folder = a.out / r["id"]
        folder.mkdir(exist_ok=True)
        rr, cc = [im.crop(r["box_xyxy"]) for im in images]
        # This signal orders inspection within a policy only. It is not fidelity.
        diff = ImageChops.difference(rr.filter(ImageFilter.GaussianBlur(.6)),
                                     cc.filter(ImageFilter.GaussianBlur(.6)))
        signal = sum(ImageStat.Stat(diff).mean) / 3
        scale = min(a.zoom, 1800 / max(rr.size))
        size = (max(1, round(rr.width * scale)), max(1, round(rr.height * scale)))
        raw = {"source": rr, "candidate": cc, "overlay": Image.blend(rr, cc, .5),
               "difference": diff.point(lambda v: min(255, v * 4))}
        for name, im in raw.items():
            im.resize(size, Image.Resampling.LANCZOS).save(folder / (name + ".png"))
        sheet = Image.new("RGB", (size[0] * 3, size[1] + 25), "#e9efed")
        draw = ImageDraw.Draw(sheet)
        for i, name in enumerate(("source", "candidate", "overlay")):
            with Image.open(folder / (name + ".png")) as im:
                sheet.paste(im, (size[0] * i, 25))
            draw.text((size[0] * i + 8, 6), name.upper(), fill="#173d41")
        sheet.save(folder / "review_strip.png")
        # Wipe keyframes make the animation's intermediate states inspectable.
        for percentage in (25, 50, 75):
            wipe = cc.copy()
            cut = round(rr.width * percentage / 100)
            wipe.paste(rr.crop((0, 0, cut, rr.height)), (0, 0))
            wipe.resize(size, Image.Resampling.LANCZOS).save(folder / f"wipe_{percentage}.png")
        record = dict(r, blurred_rgb_difference=round(signal, 4),
                      status="needs_visual_review", correction_verified=False)
        records.append(record)
        title = html.escape(r.get("name", r["id"]))
        checks = "".join("<li>" + html.escape(str(s)) + "</li>" for s in r["checks"])
        tolerance = html.escape(r.get("tolerance", "Check against the fidelity requirements of the current task."))
        gid = r["id"]
        cards.append(f'''<article id="{gid}" data-policy="{r['policy']}">
<h2>{title}</h2><p class="policy">{NAMES[r['policy']]}</p><ul>{checks}</ul><p>{tolerance}</p>
<div class="wipe"><img src="{gid}/candidate.png" alt="Candidate">
<img class="source" src="{gid}/source.png" alt="Source"><span class="divider"></span></div>
<div class="controls"><label>Source coverage <input aria-label="Source coverage" type="range" min="0" max="100" value="50"></label>
<button class="blink">Alternate images</button><button class="stop">Stop alternating</button></div>
<div class="pair"><figure><img src="{gid}/overlay.png" alt="Translucent overlay"><figcaption>50% overlay: inspect contour and endpoint drift</figcaption></figure>
<figure><img src="{gid}/difference.png" alt="Difference signal"><figcaption>Lightly blurred RGB difference ×4, for locating differences only</figcaption></figure></div>
<p><a href="{gid}/review_strip.png">Static keyframe comparison</a> · <a href="{gid}/wipe_25.png">25%</a> · <a href="{gid}/wipe_50.png">50%</a> · <a href="{gid}/wipe_75.png">75%</a></p></article>''')

    order = sorted(records, key=lambda r: (POLICIES[r["policy"]], -r["blurred_rgb_difference"]))
    result = {"canvas": list(ref.size), "reference_sha256": hashlib.sha256(a.reference.read_bytes()).hexdigest(),
              "candidate_sha256": hashlib.sha256(a.candidate.read_bytes()).hexdigest(),
              "alignment": "Caller asserts common canvas registration; equal sizes checked, no local alignment applied.",
              "warning": "Differences propose where to look; all mechanism/uncertain regions require visual review regardless of score. Scores never establish semantic importance or pass/fail.",
              "suggested_review_order": [r["id"] for r in order], "regions": records}
    (a.out / "review_queue.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    nav = " · ".join(f'<a href="#{r["id"]}">{html.escape(r.get("name",r["id"]))}</a>' for r in order)
    document = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review Local Differences by Information Importance</title><style>
body{font:16px/1.7 system-ui,sans-serif;color:#203d43;background:#eef3f1;margin:0}main{max-width:1160px;margin:30px auto;padding:24px}article{background:white;padding:25px;margin:28px 0;border:1px solid #d6e2de;border-radius:12px}h1{font-size:32px}h2{font-size:23px}.policy{color:#176f71;font-weight:650}.note{background:#fff4dd;padding:16px;border-left:4px solid #c79e47}.wipe{position:relative;max-width:850px;margin:20px auto;background:white}.wipe img{display:block;width:100%}.source{position:absolute;inset:0;clip-path:inset(0 50% 0 0)}.divider{position:absolute;left:50%;top:0;bottom:0;background:#117875;width:2px}.controls{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}button{padding:8px 14px;border:1px solid #9dbbb4;background:white;color:#176567;border-radius:6px}input{accent-color:#176d6c}.pair{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:20px}.pair img{width:100%}figure{margin:0}figcaption{font-size:13px;color:#627574}a{color:#17696b}nav{line-height:2}img{max-width:100%}@media(max-width:600px){main{padding:12px}.pair{grid-template-columns:1fr}}
</style><main><h1>Review Local Differences by Information Importance</h1><p>Establish key relationships from the source first, then use differences to narrow inspection. Wipes, alternating images, translucent overlays, and static keyframes provide complementary views.</p><p class="note">This evidence awaits visual review; it is not an automatic acceptance result. Generating the page or calculating differences does not mean an agent has inspected it or that mechanism relationships are correct. Permission to vary display assets applies only within the agreed scope.</p><nav>'''+nav+"</nav>"+"".join(cards)+'''<p><a href="review_queue.json">Machine-readable review queue</a></p></main><script>
for(const card of document.querySelectorAll('article')){const range=card.querySelector('input'),src=card.querySelector('.source'),line=card.querySelector('.divider');let timer=null;const set=v=>{src.style.clipPath=`inset(0 ${100-v}% 0 0)`;line.style.left=v+'%'};range.oninput=()=>{clearInterval(timer);set(range.value)};card.querySelector('.blink').onclick=()=>{clearInterval(timer);let source=false;set(100);timer=setInterval(()=>{set(source?100:0);source=!source},850)};card.querySelector('.stop').onclick=()=>{clearInterval(timer);set(range.value)};document.addEventListener('visibilitychange',()=>{if(document.hidden){clearInterval(timer);set(range.value)}})}
</script></html>'''
    (a.out / "index.html").write_text(document)
    print(json.dumps({"regions": len(records), "html": str(a.out / "index.html"),
                      "all_statuses": "needs_visual_review"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
