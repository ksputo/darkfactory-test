# Shared module interfaces

## Purpose

Build a local factory in this repository. Its worker, review panel, and judge are Strands agents that call Amazon Bedrock. The worker runs the application's own checks after every attempt and retries from the failures it caused; outside the worker, back pressure comes only from agents: the panel, the quorum they form, and the judge. Quorum, policy, and state are deterministic Python. Implement only the current module and retain earlier behavior. The guide relies on entry points, saved files, and exit codes, not on function names or internal modules.

The supplied `specs/`, `tasks/`, `tests/`, `factory_ui/`, `pyproject.toml`, and `uv.lock` are inputs to the exercise. Keep the specs, the checkpoint tests, and the UI intact. Use OpenCode in this repository to build the factory; the factory itself never calls OpenCode. Excalidraw edits happen only through the factory worker. A checkpoint uses local substitutes in a temporary directory and makes no model calls. Real application checks still have to run on the actual candidate.

## Project layout

- This repository is a `uv` project. `pyproject.toml` pins `strands-agents`, `strands-agents-tools`, `textual`, and `boto3`. Run everything through `uv run`; do not add dependencies.
- `uv run factory.py ...` is the factory entry point. `uv run factory-ui` starts the supplied Textual UI.
- `uv run tests/checkpoint.py MODULE` runs the checkpoint for one module.
- Locate the factory root from the entry-point file, regardless of the caller's working directory.
- Resolve the application from `EXCALIDRAW_DIR`, defaulting to `$HOME/environment/excalidraw`.
- Resolve the Bedrock model ID from `FACTORY_MODEL`, defaulting to `global.anthropic.claude-sonnet-5-5`. The region comes from `AWS_REGION`. All agents use the same model.
- Keep run IDs within `runs/`; reject path traversal. Runtime records are excluded from Git. Catch-up tags contain factory code only.

## Command surface

`uv run factory.py` with no arguments prints the supported command names, one per line, to stdout, and exits zero. The UI reads this list to show what is wired. Each module extends it:

| Module | Commands added |
|---|---|
| 20 | `work TASK_FILE [OUTPUT_DIR]`, `loop` |
| 30 | `record REQUEST_FILE [WORKER_DIR]`, `show RUN_ID` |
| 40 | `review RUN_ID`, `judge RUN_ID` |
| 50 | `decide RUN_ID` |
| 60 | `recover RUN_ID`, `resume RUN_ID`, `run REQUEST_FILE` |

Commands return zero only on success. `decide` returns zero only for `ready`. Malformed inputs, missing evidence, and invalid transitions return nonzero with a useful message on stderr. Commands that create a run print exactly one run ID to stdout. Every other diagnostic goes to stderr.

## Worker, introduced in module 20

`work TASK_FILE [OUTPUT_DIR]` runs one task to a checked, committed candidate. Relative paths resolve from the factory root. With no output argument, create a unique `runs/worker-*` directory, including when two calls start in the same second. Refuse a dirty checkout or an output directory that already contains logs. The worker is the only stage that runs the application's checks; everything after it reads the evidence the worker saved.

Before module 30 creates `policy.json`, use the initial base `afa3a653fc5d2b742adcbd5a6063187b056d2419`. Once the policy file exists, read its base for each `work` call.

### Attempt

One attempt is a fresh Strands `Agent` with the `file_read`, `file_write`, `editor`, and `shell` tools, working from the application checkout. Its system prompt tells it to inspect the source, implement the task, add meaningful tests, keep dependencies and configuration unchanged, create one local commit, and that it runs unattended with no terminal. The user message is the task file text; on a retry it is the task file text followed by the brief from the previous attempt. Each attempt has no prior messages. Stream the complete agent output to `OUTPUT_DIR/logs/worker.log`.

The agent runs with no human at the keyboard, so the factory removes every way a child process can wait for one: tool consent is bypassed (`BYPASS_TOOL_CONSENT=true`), pagers are disabled (`GIT_PAGER=cat`, `PAGER=cat`), Git never prompts for credentials or opens an editor (`GIT_TERMINAL_PROMPT=0`, `GIT_EDITOR=true`), and `CI=true` tells build tools the same. The `editor` tool writes no `.bak` files (`EDITOR_DISABLE_BACKUP=true`), so the clean-checkout gate judges the agent's work and not the tool's leftovers. The factory also bounds every tool result that reaches a model: a result over 24,000 characters is cut to its head and tail with a notice that tells the agent to read a smaller piece. One oversized directory listing or test log must not end an attempt with a context overflow. This bound applies to every agent the factory starts, including the review seats and the judge.

After the agent finishes, require a clean checkout and a `HEAD` that moved to a new commit. A finished agent without a committed candidate ends `work` with `exit` 1 and no further attempt. Tool permissions allow local work; they do not provide a hard sandbox.

### Checks

After every committed attempt the factory, not the agent, verifies the candidate:

1. Compute `changed_paths` as the sorted Git paths between the policy `base_revision` and the new `HEAD`. Fail immediately when any path is protected (dependency manifests, lockfiles, `.github/`, `.yarn/`, lint, format, typecheck, build, and test configuration, snapshots, and fixtures outside the task's own test). A protected-path failure is terminal: `work` exits nonzero and does not retry.
2. Create `OUTPUT_DIR/verify` as a detached Git worktree at the new `HEAD`.
3. Invoke `bash check-change.sh VERIFY_DIR LOG_DIR` from the factory, or the executable at `FACTORY_CHECKER` with the same two absolute arguments when set. This override lets checkpoint tests exercise the controller without Yarn or network access.
4. Retain six log/exit pairs in `LOG_DIR`, named `install`, `typecheck`, `code`, `other`, `build`, and `diagram-audit`. Each `.exit` is an integer and each `.log` contains the actual command output.
5. Write `OUTPUT_DIR/check.json` as `{proof, evidence_hash, checker_exit}`. The proof has `base_revision`, `candidate_revision`, `changed_paths`, `verify_head`, `verify_clean` (true), and `commands`, an array in the six-name order above with `name`, `exit`, and `log_hash` per entry. `evidence_hash` hashes the proof.
6. Remove the verify worktree.

An attempt passes when `checker_exit` and all six exit values are zero.

### Retry

When an attempt fails a check, move that attempt's `logs/`, `check.json`, and `worker.log` into `OUTPUT_DIR/attempts/N/` (N starting at 1) and write `OUTPUT_DIR/attempts/N/brief.md` there: the names of the failed commands, the last 40 lines of each failed command's log, and the changed paths. Start the next attempt with that brief appended to the task text. The candidate from the failed attempt stays committed; the next attempt builds on it. Allow at most three attempts per `work` call.

### Result

`OUTPUT_DIR/worker.json` holds `task`, `base_revision`, `candidate_revision` (the final `HEAD`), `exit`, `model`, and `attempts`, an array with one entry per attempt containing `attempt`, `candidate_revision`, `checker_exit`, and `failed` (the names of commands with nonzero exit). The final attempt's evidence lives at `OUTPUT_DIR/logs/` and `OUTPUT_DIR/check.json`. `exit` is zero only when the final attempt passed. When three attempts fail, the last candidate stays committed, `exit` is nonzero, and `work` returns nonzero: this is the point where a human reads the brief.

`base_revision` is the policy base used for the checks. When an attempt ends before checks can run, its `checker_exit` is null and `failed` is empty. Archive only attempts that precede another attempt; retain the final failed attempt and its `brief.md` at the top level.

When `FACTORY_WORKER` is set, invoke that executable as `FACTORY_WORKER APP_DIR TASK_FILE LOG_DIR BRIEF_FILE` instead of a Strands agent and treat its exit status as the agent result. `BRIEF_FILE` is the empty string on the first attempt and the path of the previous attempt's `brief.md` afterwards. Checkpoint tests use this to substitute a worker that commits a known change and a checker that fails once and then passes.

`loop` runs `tasks/unbound-arrows.md`, then `tasks/diagram-audit.md`, each through `work` with its own output directory inside one unique `runs/loop-*` directory. Stop on the first failure.

## State format, introduced in module 30

`record REQUEST_FILE [WORKER_DIR]` creates `runs/RUN_ID/state.json` from the committed application `HEAD` and the worker's evidence. `WORKER_DIR` defaults to the most recent `runs/worker-*` directory whose `worker.json` names the application `HEAD` as its `candidate_revision`; fail when none matches or when that worker's `exit` is nonzero. A change without passing worker evidence cannot be recorded. Require a clean target, a committed nonempty diff against the policy base, and an ancestor base revision. Copy the worker's `logs/`, `check.json`, `worker.json`, and `attempts/` into `runs/RUN_ID/`. Write a temporary file, flush it, and atomically replace the state file. Store the request text separately at `runs/RUN_ID/request.md`.

Required identity fields are `run_id`, `repo` (absolute application path), `request` (absolute saved request path), `request_hash`, `policy`, `policy_hash`, `base_revision`, `candidate_revision`, and `changed_paths` (sorted Git paths). The same write saves `check` from the copied `check.json`; its `candidate_revision` and `changed_paths` must equal the identity fields. `status` starts as `recorded`. Later modules add `reviews`, `quorum`, `judge`, and `decision` to this same object. Preserve earlier fields.

`policy.json` has exactly four fields: `base_revision` (full Git revision), `max_changed_files` (positive integer, initially 8), `required_reviewers` (3), and `required_approvals` (integer 1 through 3, initially 2). The initial base is `afa3a653fc5d2b742adcbd5a6063187b056d2419`. Snapshot the policy during `record`; later edits apply to future runs. The filter exercise changes the base to the accepted Diagram Audit candidate.

Hashes use SHA-256 lowercase hex. Hash file bytes directly. Hash structured values as UTF-8 JSON with sorted keys, separators `,` and `:`, and Python's default ASCII escaping. `policy_hash` hashes the policy snapshot. `record_hash` hashes the object containing exactly the nine identity fields listed above. Validate these hashes, the saved request, and the check evidence (re-read every `.log` and `.exit` and compare with the proof) before advancing a run. These checks detect changed local evidence; they are not signatures or an isolation boundary.

`show RUN_ID` re-validates every hash present in the state (record, check evidence, reviews, judge, decision) and prints the state as JSON. It returns nonzero with the first mismatch named when any saved evidence no longer matches its files. The UI uses this exit status to color a run green or red; the UI never computes a hash or a verdict itself.

## Evidence format, introduced in module 40

### Panel

`review RUN_ID` requires valid, passing check evidence. Create `runs/RUN_ID/verify` as a detached Git worktree at `candidate_revision` when it is absent, and confirm it is clean at that revision. Run three seats, `intent`, `failure-modes`, and `operability`, in that order. Each seat is a fresh Strands agent with only the `file_read` tool, working from the verify worktree. The seat prompt is `reviews/SEAT.md` followed by the run's `candidate.diff` and `check.json`. Seats never see each other's output. Save the prompt text in `review-prompts/SEAT.md`, the diff in `candidate.diff`, and the result in `reviews/SEAT.json` under the run directory.

Obtain each vote as structured output with exactly these fields: `reviewer` (the seat name), `candidate_revision`, `evidence_hash`, `decision` (`approve` or `rework`), `reason` (nonempty), and `claims` (array of `{path, note}` where `path` is a candidate path or the literal `evidence`). Reject a vote whose seat, revision, or evidence hash does not match the run, or whose `claims` reference a path outside `changed_paths`. Save the three validated votes under `state.reviews`, keyed by seat. A partial attempt is retained; record a new run after correcting its cause.

When `FACTORY_REVIEWER` is set, invoke that executable as `FACTORY_REVIEWER VERIFY_DIR LOG_DIR SEAT OUTPUT_JSON PROMPT_FILE` instead of an agent and read the vote from `OUTPUT_JSON`. Validation is identical.

### Quorum and judge

`judge RUN_ID` requires three valid reviews and valid check evidence. First compute `quorum` with integer logic only: `{required, approvals, votes: {seat: decision}, passed}` where `passed` is `approvals >= required_approvals`. Save it under `state.quorum`. No model output can change it.

Then run the judge, a fresh Strands agent with only `file_read`, working from the verify worktree. Its prompt is `reviews/judge.md`, the quorum object, the three votes, and `check.json`. Obtain a structured `judge` object with exactly `candidate_revision`, `evidence_hash`, `review_hash` (hash of the three review objects keyed by seat), `decision` (`approve` or `rework`), `reason` (nonempty), and `brief` (object or null). Save it under `state.judge` with `judge_hash` hashing those six fields.

Routing is fixed by the quorum, not by the judge:

- Quorum passed: the judge may return `approve` or `rework`.
- Quorum failed: the judge may return only `rework`. Reject an `approve` and return nonzero without saving.

A `rework` decision must carry a `brief` with `failed_seats` (array of seat names that voted `rework`), `excerpts` (array of strings, each at most 400 characters, at most 8 entries), `base_revision`, `candidate_revision`, `allowed_paths` (subset of `changed_paths`), and `budget_remaining` (integer, starts at 2 and decrements per rework on the same request). On `rework`, also write the brief as Markdown to `runs/RUN_ID/rework-brief.md` and create `tasks/rework-RUN_ID.md` containing the original request followed by the brief, so the worker can take it as a new task. `budget_remaining` of zero writes the brief but no task file. The judge's brief is semantic: the checks already passed, so it names what the panel found, never a failed command.

Set `status` to `judged`. When `FACTORY_JUDGE` is set, invoke that executable as `FACTORY_JUDGE RUN_DIR OUTPUT_JSON PROMPT_FILE` and read the judge object from `OUTPUT_JSON`. Validation and routing are identical.

## Decision format, introduced in module 50

`decide RUN_ID` requires valid check evidence, reviews, quorum, and judge. The verdict is a pure function of saved facts:

- `needs-human` when `len(changed_paths) > max_changed_files`.
- `needs-rework` when `quorum.passed` is false or `judge.decision` is `rework`.
- `ready` otherwise.

Save `decision` with `status`, `reason`, `evidence_hash`, `review_hash`, `judge_hash`, and `policy_hash`. Add `decision_hash`, hashing those six fields. Set the top-level `status` to the decision status. Once a decision exists, successful reuse by `review`, `judge`, `decide`, or `resume` must preserve that terminal status. Repeated decisions on unchanged evidence return the same object. Changed evidence cannot silently replace a completed decision.

No command merges, pushes, releases, or deploys the application.

## Recovery, introduced in module 60

`recover RUN_ID` re-validates every saved stage in order (record, check evidence, reviews, quorum, judge, decision), removes nothing, and reports the first stage whose evidence is missing or invalid on stderr. `resume RUN_ID` continues from the first missing stage: `review`, then `judge`, then `decide`, reusing valid evidence and preserving a terminal status. The check evidence came from the worker; when `recover` finds it invalid, `resume` returns nonzero and the fix is to run `work` again and record a new run. `run REQUEST_FILE` chains `work`, `record` on that worker directory, and `resume`, and prints the run ID.

## Substitutes used by checkpoints

| Variable | Replaces | Arguments |
|---|---|---|
| `FACTORY_WORKER` | worker agent | `APP_DIR TASK_FILE LOG_DIR BRIEF_FILE` |
| `FACTORY_CHECKER` | `check-change.sh` | `VERIFY_DIR LOG_DIR` |
| `FACTORY_REVIEWER` | seat agent | `VERIFY_DIR LOG_DIR SEAT OUTPUT_JSON PROMPT_FILE` |
| `FACTORY_JUDGE` | judge agent | `RUN_DIR OUTPUT_JSON PROMPT_FILE` |

Substitutes exist so checkpoints can run without Bedrock. The factory validates their output with the same rules it applies to agent output.
