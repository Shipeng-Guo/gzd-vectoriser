# Independent Visual Review: Return Known Issues to Repair

Run after the production team's self-review and before final delivery; recheck the current version after every modification. This stage uses a reviewer with an independent context, while the production agent remains free to choose drawing and repair methods. Anonymity is useful for controlled experiments; ordinary tasks depend on isolation from production history, dedicated observation, and returning findings to repair.

## Delegation and Observation

Use the available subagent or delegation mechanism to create a reviewer without prior context (for example, `fork_turns="none"`). Provide only the review packet and a directory for writing review results. The reviewer must not read the production process, previous pass statements, or other teams' results, and must not modify the drawing. If no independent reviewer is available, leave acceptance pending; do not relabel the production team's self-review as an independent review.

There are two review tasks:

- **Fresh discovery:** Inspect only the source, the current actual render, the canvas, source-derived requirements, and changes permitted in advance. Inspect the full image first, then cover every region. Enlarge complete objects and their neighborhoods rather than cutting off judgment at tile boundaries. Check omissions, membership, separation/connections, endpoints, text, shape, position, color, stroke width, lightness, and occlusion. Actively look for objects present in the source but absent from the artifact. Do not set an error quota, invent differences to find faults, or tell the reviewer where errors are expected.
- **Issue recheck:** Also provide the persistent issue list. Independently confirm the disposition of each ID, including the object's other attributes and effects on neighboring objects. The repairer's statements do not count as evidence of passing. Incorrect nominations may be explicitly rejected based on the source. Allowed differences must cite permission registered in advance for the task; repeated failure cannot justify relaxing it.

Use the two tasks in this order: discovery → record findings → repair → recheck issues in the current version → fresh full-image discovery. New issues in the final full-image discovery pass return to the loop. The independent reviewer may recheck current evidence without reading the drawing code.

For similar or repeated members, compare relative attributes; do not pass them merely because they belong to the same color or shape category. For example, separately confirm that source lightness differences between members remain present; completing shape repairs does not establish that color relationships have been rechecked. Require such distinctions only when supported by the source, without assuming that all repeated members should differ.

Freeze the candidate after delegation and wait until the current observation record is successfully entered in the ledger before modifying it. Read-only observations may run in parallel, but the production agent must not modify files under review at the same time. If a file changes before observations are recorded, preserve the original observation file and rebind to the current version; do not bypass invalidation checks.

A single composite image is insufficient for hidden underlays, moving members, or occlusion relationships. Use `--views` below to attach isolated, hidden, or moved screenshots of the current artifact. Require the reviewer to inspect them and cite the views in the corresponding conclusions. Do not provide old pass statements; structural probes must still be completed separately.

## General Review Prompt Template

> Check reproduction accuracy against the source, current candidate, and source-derived requirements in the review packet. Read only the packet, not production history, previous pass conclusions, or other artifacts. Actually inspect the full image and enlarge complete objects and their neighborhoods region by region; overall similarity cannot compensate for local content or relationship errors. Report actionable, locatable issues with source coordinates, observable differences, and image evidence. Mark unconfirmed findings as uncertain. Honor permissions registered in advance while verifying invariants. During fresh discovery, do not narrow the search using an old issue list; during recheck, give a disposition for every persistent ID. Follow the packet's report-template.json and do not modify candidate files.

Include the interface enums when delegating: coverage regions use `pass` / `fix_required` / `uncertain`; requirement checks use `pass` / `fail` / `uncertain`; known-issue dispositions use `fixed` / `rejected` / `allowed_difference` / `unresolved`. Evidence uses `source` and `candidate`, with `view:ID` for attached views. These specify the format without predetermining judgments.

## Version and Issue Constraints

`scripts/independent_review.py` stores independent records in the same review ledger. Review packets bind the source, SVG, actual render, and requirements; changing any file prevents an old independent pass from releasing the new version. Existing IDs persist and must not be removed merely because a later review does not mention them again. Any unresolved or uncertain issue, missing observation, or stale-version review blocks formal delivery.

Identity fields record actual delegation relationships and do not replace context isolation. The tools validate evidence and state; they do not pretend to inspect images on the agent's behalf. Reviewers must actually observe, without fabricating batches of passing judgments.

Use `independent_review.py --help` and the generated report template as the authority for API commands and schemas.

## Command Interface

Specify the actual maker identity when initializing a new ledger; the independent gate is required by default:

```sh
python scripts/review_loop.py init --ledger review.json --scan scan-r01/scan.json \
  --artifact drawing.svg --maker-id MAKER_SESSION_ID
```

Migrate an older ledger only once, preserving all known failure history:

```sh
python scripts/independent_review.py attach --ledger review.json --maker-id MAKER_SESSION_ID
```

Register issues already confirmed by reports, the user, or other evaluations immediately; do not wait for another scan to rediscover them:

```json
[{"id":"external-01","title":"Connection gap","box_xyxy":[100,120,220,240],
  "note":"The source connection is continuous, but the current candidate has a break.","evidence":"/absolute/path/observed.png"}]
```

```sh
python scripts/independent_review.py flag --ledger review.json --findings findings.json
python scripts/independent_review.py packet --ledger review.json --phase discovery --output independent-discovery-01
```

Give this directory to a reviewer with an isolated context, asking them to complete its `report-template.json` and save a new file. Record the actual review results:

```sh
python scripts/independent_review.py record --ledger review.json \
  --packet independent-discovery-01/packet.json --report independent-discovery-01/observed.json
```

The production agent modifies the artifact based on registered issues, actually renders it, scans it, and runs `rebase`. After repairing the original issues, generate a `--phase recheck` packet for the independent reviewer. The recheck report must explicitly dispose of every persistent ID; omission does not mean an issue has disappeared.

When structural observation images are available, prepare `views.json` with paths relative to that JSON file and a hash from the current SVG:

```json
[{"id":"underlay-isolated","path":"probe/underlay-only.png",
  "artifact_sha256":"CURRENT_SVG_SHA256","description":"Isolated underlay with the foreground hidden"}]
```

Add `--views views.json` when generating the packet. The tool accepts only decodable PNGs, verifies the artifact hash, and copies the images; recording, acceptance, and formal report packaging verify image fingerprints again. Keep `source` and `candidate` in the report's `evidence`, adding `view:underlay-isolated` for items involving that view. Additional views are unnecessary when there are no structural issues.

```sh
python scripts/independent_review.py packet --ledger review.json --phase recheck --output independent-recheck-01
python scripts/independent_review.py record --ledger review.json \
  --packet independent-recheck-01/packet.json --report independent-recheck-01/observed.json
```

After the recheck passes, generate another discovery packet for the current version and cover the entire image again. New findings continue the loop; finally run the main gate and build the formal report:

```sh
python scripts/independent_review.py check --ledger review.json
python scripts/review_loop.py check --ledger review.json --scan final-scan/scan.json --artifact drawing.svg
```

The review packet includes current file fingerprints, and the template lists required coverage rows and source-derived requirements. Do not manually copy schemas or fill batches with default passes. Maker and reviewer identities must genuinely differ; `independence_attestation` records actual observation in isolation. Independent review does not replace the existing full-difference observation, current-version structural probes, or outer scan.
