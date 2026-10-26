#!/usr/bin/env python3
"""Read-only SVG inventory and explicit selection-group membership checks.

Standard library only. Does not render, resolve CSS/use, call an editor, fetch
references, or judge visual fidelity. Exit 2 means a structural check failed.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


LEAVES = {"path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
          "text", "image", "use", "foreignObject"}
DEFINITIONS = {"defs", "clipPath", "mask", "marker", "pattern", "symbol",
               "linearGradient", "radialGradient", "metadata"}
INKSCAPE = "http://www.inkscape.org/namespaces/inkscape"
XLINK = "http://www.w3.org/1999/xlink"


def local(tag):
    return tag.rsplit("}", 1)[-1]


def audit(path, manifest=None):
    raw = path.read_bytes()
    root = ET.fromstring(raw)
    errors, warnings = [], []
    if local(root.tag) != "svg":
        raise ValueError("Root element is not svg")
    all_nodes = list(root.iter())
    id_counts = Counter(n.get("id") for n in all_nodes if n.get("id"))
    duplicates = sorted(k for k, v in id_counts.items() if v > 1)
    if duplicates:
        errors.append({"duplicate_ids": duplicates})
    leaves, groups = [], []
    group_members = defaultdict(list)

    def visit(node, ancestors=(), hidden=False):
        tag = local(node.tag)
        if tag in DEFINITIONS:
            return
        style = dict(p.split(":", 1) for p in node.get("style", "").split(";") if ":" in p)
        style = {k.strip(): v.strip() for k, v in style.items()}
        # A hint only; stylesheet rules and visibility overrides are not resolved.
        hidden = hidden or style.get("display", node.get("display")) == "none"
        hidden = hidden or style.get("visibility", node.get("visibility")) in {"hidden", "collapse"}
        try:
            hidden = hidden or float(style.get("opacity", node.get("opacity", "1"))) == 0
        except ValueError:
            pass
        if tag == "g":
            index = len(groups)
            groups.append({"id": node.get("id"), "depth": len(ancestors) + 1,
                           "inkscape_layer_metadata": node.get(f"{{{INKSCAPE}}}groupmode") == "layer"})
            ancestors = ancestors + (index,)
        if tag in LEAVES:
            entry = {"id": node.get("id"), "type": tag,
                     "ancestor_groups": [groups[i]["id"] for i in ancestors],
                     "hidden_hint": hidden}
            if tag == "text":
                entry["text"] = "".join(node.itertext())
            if tag in {"image", "use"}:
                href = node.get("href", node.get(f"{{{XLINK}}}href", ""))
                entry["reference"] = href[:100] + ("…" if len(href) > 100 else "")
                entry["reference_kind"] = "embedded" if href.startswith("data:") else "local-id" if href.startswith("#") else "external-or-file"
            leaves.append(entry)
            for index in ancestors:
                group_members[index].append(entry)
            return
        for child in node:
            visit(child, ancestors, hidden)

    visit(root)
    for i, group in enumerate(groups):
        members = group_members[i]
        counts = Counter(x["type"] for x in members)
        group.update({"leaf_count": len(members), "leaf_types": dict(counts),
                      "members": [x["id"] for x in members]})
        if counts.get("text", 0) >= 3 and len(counts) == 1:
            warnings.append({"text_only_group_review_needed": group["id"],
                             "reason": "May collect unrelated labels; review intended selection units."})
    counts = Counter(x["type"] for x in leaves)
    missing_ids = sum(x["id"] is None for x in leaves)
    if missing_ids:
        warnings.append({"scene_leaves_without_ids": missing_ids})
    if counts.get("image"):
        warnings.append("Image nodes exist. Check their contents, visibility and reference-only status; do not claim an all-vector document from this inventory.")
    xml_counts = Counter(local(n.tag) for n in all_nodes)
    if any(xml_counts[t] for t in ("style", "use", "mask", "clipPath", "filter", "foreignObject")):
        warnings.append("CSS/references/effects may alter visibility, geometry or selection. This inventory does not resolve them.")
    if any(g["inkscape_layer_metadata"] for g in groups):
        warnings.append("Inkscape layer metadata is present; native layers in other editors are unverified.")

    manifest_checked = manifest is not None
    if manifest_checked:
        if not isinstance(manifest, dict) or not isinstance(manifest.get("groups"), list):
            raise ValueError("Manifest requires a groups list")
        groups_by_id = {g["id"]: g for g in groups if g["id"]}
        claimed = []
        declared_groups = []
        for requested in manifest["groups"]:
            if not isinstance(requested, dict) or not isinstance(requested.get("id"), str):
                raise ValueError("Every manifest group requires a string id")
            gid, expected = requested["id"], requested.get("members")
            if not isinstance(expected, list) or not all(isinstance(x, str) for x in expected):
                raise ValueError("Group members must be a list of leaf IDs")
            declared_groups.append(gid)
            claimed.extend(expected)
            actual = groups_by_id.get(gid)
            if actual is None:
                errors.append({"missing_group": gid})
            elif Counter(actual["members"]) != Counter(expected):
                errors.append({"group_member_mismatch": gid,
                               "expected": expected, "actual": actual["members"]})
        duplicate_groups = [k for k, v in Counter(declared_groups).items() if v > 1]
        if duplicate_groups:
            errors.append({"duplicate_manifest_groups": duplicate_groups})
        ungrouped = manifest.get("ungrouped_objects", [])
        if not isinstance(ungrouped, list) or not all(isinstance(x, str) for x in ungrouped):
            raise ValueError("ungrouped_objects must be a list of leaf IDs")
        claimed.extend(ungrouped)
        for leaf in leaves:
            if leaf["id"] in ungrouped and leaf["ancestor_groups"]:
                errors.append({"declared_ungrouped_but_grouped": leaf["id"]})
        actual_ids = Counter(x["id"] for x in leaves)
        claimed_ids = Counter(claimed)
        if actual_ids != claimed_ids:
            errors.append({"manifest_coverage_mismatch": {
                "unaccounted_scene_ids": list((actual_ids - claimed_ids).elements()),
                "excess_or_missing_claimed_ids": list((claimed_ids - actual_ids).elements())}})
        reused = [k for k, v in claimed_ids.items() if v > 1]
        if reused:
            errors.append({"leaves_claimed_more_than_once": reused})

    return {
        "source": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(),
        "canvas": {k: root.get(k) for k in ("width", "height", "viewBox")},
        "scene_leaf_count": len(leaves), "scene_leaf_types": dict(counts),
        "scene_group_count": len(groups), "xml_element_counts": dict(xml_counts),
        "groups": groups, "leaves": leaves,
        "manifest_checked": manifest_checked,
        "structural_checks_passed": not errors, "errors": errors, "warnings": warnings,
        "limits": ["Counts include hidden scene objects; hidden_hint is not computed visibility.",
                   "Definition contents are excluded; use is counted as an instance, not expanded.",
                   "No visual fidelity, semantic correctness, native layer or mouse-selection verification."]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("svg", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.output and args.output.resolve() in {args.svg.resolve(), args.manifest.resolve() if args.manifest else None}:
        parser.error("Output must not overwrite SVG or manifest")
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
        result = audit(args.svg, manifest)
    except (OSError, ET.ParseError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps({k: result[k] for k in ("scene_leaf_count", "scene_group_count", "manifest_checked", "structural_checks_passed")}, ensure_ascii=False))
    else:
        print(rendered, end="")
    return 0 if result["structural_checks_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
