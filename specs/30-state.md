# Module 30: Save the candidate

## Need

The worker has produced a commit and the evidence that its checks passed. Later stages need an exact candidate, request, and check evidence, even if the working branch moves. Add factory-owned state that the UI can list and re-verify.

## Implement

Retain module 20. Read the shared interfaces and add `record` and `show` to `factory.py`. Create `policy.json` with the four specified fields and initial values. The participant changes the base for a later feature; initial recording uses the pinned baseline.

`record REQUEST_FILE [WORKER_DIR]` validates the request, clean target, policy, base ancestry, and a nonempty base-to-HEAD diff. When `WORKER_DIR` is absent, use the most recent `runs/worker-*` directory whose `worker.json` names the application HEAD as its candidate; fail when none exists or when that worker exited nonzero. A change without passing worker evidence cannot be recorded.

Generate a unique run ID, save a copy of the request, copy the worker's `logs/`, `check.json`, `worker.json`, and `attempts/` into the run directory, and atomically save the identity fields, hashes, and the `check` object in one write. The `check` object's candidate and changed paths must equal the identity fields. Print only the ID to stdout. Never alter the application or create its commit while recording.

`show` returns the saved JSON for an existing ID and re-validates every hash present in the state, including each check log against the proof. New application commits and edits to the original task or policy do not change that record. A changed request copy, policy snapshot, check log, or state field makes `show` exit nonzero and name the first mismatch on stderr. Refuse unsafe run IDs. Keep runtime data outside Git.

Add `record` and `show` to the no-argument command list. The UI's run selector appears when `record` is wired; it calls `show` for each run and colors the run from the exit status.

Do not add review, judge, policy evaluation, or recovery yet. Use functions and internal files that make the code readable; preserve the specified entry points and data format.

## Check

Run `uv run tests/checkpoint.py 30`. It also runs module 20 tests. State tests use local Git commits to verify identity, request and policy snapshots, copied check evidence, unique records, rejected inputs (including a worker directory whose candidate is not HEAD), and `show` detecting an edited record or an edited check log.

Then press `r` in `uv run factory-ui` to record the actual Diagram Audit candidate, and compare the saved revision shown in the run selector with Excalidraw's Git history. Keep that run ID for module 40.
