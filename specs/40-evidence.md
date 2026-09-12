# Module 40: Review and judge the saved change

## Need

A recorded commit identifies a change, and the worker's check evidence shows the application's own tests accepted it. Neither tells you whether the change does what the request meant. Add a review panel that reads the diff and the check evidence, an integer quorum over the panel, and a judge that turns a failed candidate into a bounded rework task. Everything in this module is agentic back pressure on a candidate the machine already accepted; most of the module's time belongs here.

## Implement

Retain modules 20 and 30. Add `review` and `judge` to `factory.py`, plus the three `reviews/SEAT.md` question files and `reviews/judge.md`. Use the evidence interfaces in `specs/interfaces.md`.

### Panel

Require valid, passing check evidence on the run before any seat runs; a run whose worker failed its checks is never reviewed, it is worked again. Create the detached verification worktree at the saved candidate when it is absent and confirm it matches the proof. Build each seat's prompt from its question file, the request, the candidate diff, and the check material, and save that prompt. Run the three seats in order, each as a fresh Strands agent that can only read files in the verification worktree. Obtain each vote as structured output. Seats never see each other's votes. Validate the checkout again after the panel; tool permissions are not filesystem isolation.

Create focused question files:

- Intent: detection rules, stable ordering, counts, clean state, and acceptance criteria.
- Failure modes: deleted elements, endpoint bindings, frame membership, safe URLs, accessible roles, and row activation.
- Operability: test coverage, state updates, non-mutation, theme/localization conventions, and what the check logs do and do not show.

Each question file ends by asking the seat for a decision, a reason, and claims that name the exact changed path each claim is about. Bind all votes to the candidate and evidence hash. Missing, malformed, misbound, or partial results block progress. Preserve them for diagnosis. Repeated review may reuse a complete valid set; it must not launch new seats to replace an unfavorable vote.

### Quorum and judge

`judge` first counts approvals and compares the count with `required_approvals`. That comparison is integer arithmetic over saved votes and nothing else; save it before any model runs.

Then run the judge as a fresh read-only Strands agent with `reviews/judge.md`, the quorum, the votes, and the check material. The judge explains the panel, it does not overrule it: with a passed quorum it may approve or ask for rework; with a failed quorum it may only ask for rework, and an `approve` is rejected without saving. `reviews/judge.md` tells the judge to cite the votes it relies on, and to write a rework brief that a worker can act on without reading the transcript.

A rework decision writes the brief to the run directory and creates a new task file under `tasks/` that contains the original request followed by the brief. The brief names the dissenting seats, quotes bounded excerpts from their reasons, lists the paths the worker may touch, and carries the remaining rework budget. The brief is about meaning, never about a failed command: the worker already proved the commands pass. Budget zero still records the brief but creates no task.

## Check

Run `uv run tests/checkpoint.py 40`. It includes earlier checkpoints and uses local worker, checker, reviewer, and judge substitutes to exercise identity binding, a run with failed check evidence that review refuses, a malformed vote, a failed quorum with a rejected approve, and a rework brief that produces a new task file.

Then open `uv run factory-ui` and press `v` and `j` on the recorded Excalidraw candidate. Read each seat's reason and claims, the quorum count, and the judge's reason. Generated application tests and model reviews can both miss defects; compare them with the feature's acceptance criteria in the browser.
