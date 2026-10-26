# Review State and Loop Interface

Read after scanning. `review_loop.py` stores stable IDs, current file bindings, observations, and history; the agent performs observation, repair, and rendering. Run commands from the skill directory. Use `--help`, `status`, and `queue` first to inspect the interface and pending work, without repeatedly reading the scripts or the entire ledger.

## Initialization and Single-Region Review

```sh
python scripts/review_loop.py init --ledger review.json --scan scan-r01/scan.json --artifact drawing.svg
python scripts/review_loop.py status --ledger review.json
python scripts/review_loop.py queue --ledger review.json --limit 8
python scripts/review_loop.py begin --ledger review.json --id R01
python scripts/review_loop.py record --ledger review.json --id R01 \
  --verdict fix_required --note 'The short bar endpoint shown in the source is missing; repair the corresponding connection.' \
  --evidence scan-r01/R01/pair.png
```

Use the evidence path returned for the current item by these commands; do not guess scan directory names. `fix_required` / `uncertain` locks the current issue: do not proceed directly to the next item before resolving it. Stable IDs remain bound to regions regardless of ranking changes.

After actually repairing and rendering the artifact, export the fixed region boxes, run a new scan, and update the ledger:

```sh
python scripts/review_loop.py export-regions --ledger review.json --output fixed-regions.json
python scripts/scan_differences.py --reference source.png --candidate rendered.png \
  --out scan-r02 --regions fixed-regions.json --lean
python scripts/review_loop.py rebase --ledger review.json --scan scan-r02/scan.json --artifact drawing.svg
```

If an older ledger lacks canvas data, add `--scan` to `export-regions` to specify the old scan. New issue boxes may be appended to the regions, using IDs that do not duplicate existing items. `rebase` preserves existing IDs and history, adds new nominations, and reopens changed crops; observations of unchanged crops may be reused within the inner loop. Once the SVG is bound, continue passing `--artifact` on every rescan.

View the current pair again and check the original issue, the object's other attributes, and effects on neighboring objects before recording `pass`. When there are critical `requirements`, submit all current checks:

```json
{
  "shape":{"verdict":"pass","note":"The body is closed and the opening on the right is preserved."},
  "connection":{"verdict":"pass","note":"The short bar connects to the lower edge without penetrating the body or floating apart."},
  "label":{"verdict":"pass","note":"All characters are visible and the connection does not cover the text."}
}
```

```sh
python scripts/review_loop.py record --ledger review.json --id R01 \
  --verdict pass --note 'The current shape, connection, and text have each been checked.' \
  --evidence CURRENT_PAIR_PATH --checks checks.json
```

`pass` / `allowed_difference` must use the current scan's native-resolution pair or a byte-identical copy. Enlarged views support observation but do not replace the bound evidence. The keys in `checks` must match the requirements, with a `pass/uncertain/fail` verdict for each; closing an issue requires every check to pass with a specific note. Reopen issues when requirements are added or changed. Do not substitute aggregate pixel scores, object counts, or "already modified" for judgment.

## Allowed Changes

Initialization may include `--policies policies.json` to register the scope of user-authorized changes in advance:

```json
[{"id":"display_asset","box_xyxy":[100,100,500,450],
  "reason":"The user permits replacement of this display asset",
  "allowed_changes":["surface texture"],"invariants":["identity","viewpoint","position"],
  "strict_boxes":[[220,180,280,230]]}]
```

For `allowed_difference`, add `--policy-id display_asset`. The issue box must lie within the permitted region and must not intersect strict subregions; split boxes that cross these boundaries. Invariants and `requirements` still require checking. Retain pixel differences as usual. Failed retries do not justify expanding the permitted scope.

## Batch Recording and Work Tracking

Combine only records that have already been observed individually:

```json
[{"id":"R01","verdict":"pass","note":"Specific observation and conclusion",
  "evidence":"/absolute/path/current/pair.png","checks":{}}]
```

```sh
python scripts/review_loop.py record-batch --ledger review.json --observations observed.json
```

Omit `checks` for items without requirements; complete all checks for items with requirements. `policy_id` is supported. Provide a specific note and evidence for each actual region, with no default pass. When different channels nominate the same box, an observation may be reused only if the coordinates, current crop and evidence hashes, requirements, verdict, permission, and checks all match. Do not apply a generic passing statement to different regions. Submission is atomic; handle an existing locked item first, and place any item requiring repair or marked uncertain only at the end of the batch. Reduce calls, not actual observation. Record repairs, verification, rollbacks, and tool debugging; attach object IDs and before/after evidence to repairs. Use execution records when reporting elapsed time or tokens.

## Outer Discovery Pass

After completing the local checklist, request an outer discovery pass before running a fresh scan:

```sh
python scripts/review_loop.py export-regions --ledger review.json --output fixed-regions.json
python scripts/review_loop.py start-discovery --ledger review.json --scan scan-r02/scan.json --artifact drawing.svg
python scripts/scan_differences.py --reference source.png --candidate rendered.png \
  --out discovery-r01 --regions fixed-regions.json --lean
python scripts/review_loop.py rebase --ledger review.json --scan discovery-r01/scan.json --artifact drawing.svg
```

This reopens all changed tiles, candidate regions, and coverage boxes; observe them again even when their crops have not changed. Newly discovered issues return to repair. Once local work is complete, start another fresh outer discovery pass; a pass that found issues cannot count as the final pass with no new issues.

After all current items have been handled to the required standard and no new issues need repair:

```sh
python scripts/review_loop.py finish-discovery --ledger review.json --scan discovery-r01/scan.json \
  --artifact drawing.svg --note 'Scope actually checked in this pass and its results.'
python scripts/review_loop.py check --ledger review.json --scan discovery-r01/scan.json --artifact drawing.svg
```

The check rejects stale scans, missing observations, pending repairs, incomplete outer discovery passes, invalid files or evidence, and registered structural probes that have not passed. Packaging must honor exit codes; the agent performs the actual rendering and observation.

## Independent Acceptance and Later Issues

After the outer self-review, perform an [independent visual review](independent-review.md). `review_loop.py check` also checks the independent gate; an empty local queue does not replace independent acceptance. Confirmed issues raised in reports or reviews must enter the persistent issue list and receive independent rechecks, rather than appearing only as "limitations" in the delivery report. For frozen experiments, create a separate revision and leave the original experiment results unchanged.

## Later Findings, Structural Evidence, and Recovery

Issues discovered while writing reports, during self-review, or through user feedback must be reopened rather than merely described in prose:

```sh
python scripts/review_loop.py flag --ledger review.json --id R01 \
  --note 'Specific defect in the current evidence' --evidence actual-finding.png
```

For a new location, first add a region and scan it into the ledger. Preserve frozen experiment artifacts and create a separate delivery revision. Keep genuinely unachievable requirements unresolved; do not mark them as passing merely to exit.

When occlusion checks are required, register them before testing, then import evidence of either success or failure; see [structure-checks.md](structure-checks.md) for the interface:

```sh
python scripts/review_loop.py require-probes --ledger review.json --checks occlusion.json
python scripts/review_loop.py import-probe --ledger review.json --evidence occlusion-result/result.json
```

All registered cases, directions, and sample types must be present; retest after artifact changes. Do not remove check obligations to bypass a failure.

If the SVG has already changed during an outer discovery pass and the old scan is rejected, recover by aborting while preserving history, then rescan, rebase, repair, recheck, and run a new outer discovery pass:

```sh
python scripts/review_loop.py abort-discovery --ledger review.json --id R01 \
  --note 'New issue and reason for interruption' --evidence actual-finding.png
```

This supports only `awaiting_scan/reviewing`. It preserves the interrupted state and evidence without replacing file bindings or generating a pass. Prefer flagging before modifying; do not edit the ledger manually or erase failure history.
