# Module 50: Make the routine decision

## Need

The worker's checks, the panel, the quorum, and the judge have all spoken. Express the repeatable part of accepting their verdict as a rule evaluated against saved facts.

## Implement

Retain earlier modules. Add `decide RUN_ID` to `factory.py`. Use the decision format in the shared interfaces. Keep the participant's current policy values and existing records.

Before deciding, revalidate saved identity, the recorded check evidence (all six logs and exit values against the proof), all three votes, the quorum, and the judge object. Invalid or missing evidence returns nonzero without creating a decision.

Apply the recorded policy snapshot in this order:

1. More than `max_changed_files` changed paths: `needs-human`.
2. Failed quorum, or a judge decision of `rework`: `needs-rework`.
3. Otherwise: `ready`.

Save a clear reason and the evidence, review, judge, policy, and decision hashes. Return zero only for `ready`. Repeating a decision on the same facts returns the same object. Evidence changes must not silently replace a completed result.

The routine rule is a local readiness decision. Keep merge and deployment outside this command. This module has no automated retry, duration, or inference-cost budget.

## Check

Run `uv run tests/checkpoint.py 50`. Local scenarios check readiness, rework, broad-scope escalation, missing evidence, policy snapshots, and repeat decisions.

Then press `d` in `uv run factory-ui` on the real Diagram Audit run. Compare the result with the participant's earlier judgment. Record disagreements and use the relevant repair or human path before the next request.
