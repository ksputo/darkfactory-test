# Module 20: Run a worker that checks its own work

## Need

A chat session can make a change, but repeating a task should not depend on retyping a prompt, and a committed change is not done until the application's own checks pass against it. Build the smallest factory: a command that starts one Strands worker against the application, runs the application's checks against the commit the worker made, feeds any failure back to a fresh worker, and retains every attempt. Add a loop over two application requests. The supplied UI shows the Worker box dark until this module is done.

## Implement

Read `specs/interfaces.md`. Create `factory.py` with the `work` and `loop` commands and the no-argument command listing, plus `check-change.sh`. The task files already contain human-defined Excalidraw requirements.

### Attempt

`work` validates the request, target checkout, and output path before creating an agent. Refuse a dirty checkout or an output directory with existing logs. Use a unique output directory by default, including when two calls start in the same second.

Build the worker as a Strands `Agent` on the Bedrock model from `FACTORY_MODEL`, with the `file_read`, `file_write`, `editor`, and `shell` tools, and a system prompt that tells it to inspect the source, implement the request, add meaningful tests, keep dependencies and configuration unchanged, and create one local commit. Give it the task text as its only user message; on a retry, append the previous attempt's brief. Stream the agent output to `logs/worker.log`. Each attempt is a fresh agent. The factory-building session must not start a real application worker while implementing this module.

After the agent finishes, verify that the application is clean and `HEAD` moved to a new commit. A finished agent without a committed candidate is a failure and ends the run; the checks never ran, so there is nothing to retry from. Tool permissions allow local work; they do not provide a hard sandbox.

### Checks

The factory, not the agent, decides whether the attempt passed. Compute the changed paths between the policy base and the new commit. Reject changes to dependency manifests, lockfiles, `.github/`, `.yarn/`, lint/format/typecheck/build/test configuration, snapshots, and fixture files; test fixtures created inline in the new audit test are allowed. A protected-path change ends the run without a retry, because the next attempt would start from a candidate the factory may not accept.

Create a separate, detached worktree at the new commit. `check-change.sh` runs these commands in that worktree, writes each actual log and exit value, and returns nonzero if any command fails:

| Log name | Command |
| --- | --- |
| install | `yarn install --frozen-lockfile --non-interactive` |
| typecheck | `yarn test:typecheck` |
| code | `yarn test:code` |
| other | `yarn test:other` |
| build | `yarn build:app` |
| diagram-audit | `yarn vitest --run --passWithNoTests --minWorkers=1 --maxWorkers=2 packages/excalidraw/tests/diagramAudit.test.tsx` |

The first task lands before `diagramAudit.test.tsx` exists; `--passWithNoTests` lets that attempt pass the sixth check. Once the test file exists, every attempt runs it.

A fresh dependency install belongs to this worktree; do not reuse another checkout's `node_modules`. Save `check.json` with the proof, the evidence hash, and the checker exit, then remove the worktree. Honor `FACTORY_CHECKER` as described in the interfaces so the checkpoint can substitute the script.

### Retry

When any command fails, move that attempt's logs, `check.json`, and `worker.log` into `attempts/N/` and write `brief.md` next to them: the failed command names, the last 40 lines of each failed log, and the changed paths. Nothing else; the brief is the only thing the next attempt learns from the previous one. The failed commit stays in the application history. Start the next attempt with the task text and the brief. Stop after three attempts.

`worker.json` lists every attempt with its candidate revision, checker exit, and failed command names, and reports `exit` 0 only when the final attempt passed every command. After three failures the last candidate stays committed and `work` exits nonzero. That exit is the point where a person reads the brief and decides; the factory does not try a fourth time.

Honor `FACTORY_WORKER` as described in the interfaces so the checkpoint can substitute the agent.

### Loop

`loop` runs Unbound Arrows, then Diagram Audit, each through `work` in its own output directory inside one unique loop directory. Stop when a task fails; the participant can retry that task explicitly.

## Check

Run `uv run tests/checkpoint.py 20`. The tests use substitute worker and checker programs in a temporary application. They check invocation arguments, task order, log preservation, clean commits, fresh output directories, a protected-path change that ends the run, an attempt that fails and a second attempt that passes with the brief present, and a run that exhausts its three attempts. They make no model calls.

Then start `uv run factory-ui`, select `tasks/unbound-arrows.md`, and press `w`. Watch the Worker box go live, show each attempt as it finishes, and end proven or failed. Inspect the worker log, each attempt's brief, the local commits, and the Diagram Audit browser behavior. A passing check proves the application's tests accepted the change; it does not prove the feature does what the request meant.
