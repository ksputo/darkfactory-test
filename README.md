# Build your factory

This starter contains module specs, application requests, a working Textual UI, and independent factory checkpoint tests. Use OpenCode in this directory to implement each module. The factory you build runs Strands agents on Amazon Bedrock against the separate Excalidraw checkout; it never calls OpenCode itself. The worker runs the application's own checks after every attempt and retries from its failures; outside the worker, back pressure comes from agents (panel, quorum, judge) and a small policy rule.

Start the UI with `uv run factory-ui`. Every stage is dark until the command behind it exists. The UI lights a stage when `uv run factory.py` lists its command, and colors a run green or red from the exit status of `show`. The UI computes no verdict of its own.

| Module | Spec | Checkpoint | Factory catch-up tag |
| --- | --- | --- | --- |
| Run a worker that checks its own work | `specs/20-loop.md` | `uv run tests/checkpoint.py 20` | `00-worker` |
| Save a candidate | `specs/30-state.md` | `uv run tests/checkpoint.py 30` | `01-record` |
| Review and judge | `specs/40-evidence.md` | `uv run tests/checkpoint.py 40` | `02-gate` |
| Apply policy | `specs/50-policy.md` | `uv run tests/checkpoint.py 50` | `03-policy` |
| Run and recover | `specs/60-recovery.md` | `uv run tests/checkpoint.py 60` | `04-recovery` |

Read `specs/interfaces.md` with each module. Interfaces and observable behavior are fixed; internal functions and file organization can vary. Tests run copies of your factory in temporary directories with a small Git repository and local worker, checker, reviewer, judge, and Yarn substitutes. They make no model calls and do not test the actual Excalidraw feature. Use the workshop's application exercises for that.

The packaged repository starts on `main` at `starter`. Completed implementations exist only in the catch-up tags. Follow the checkpoint page to restore factory files. Keep your application checkout and saved runs; catch-up does not supply or approve an Excalidraw change.

If a checkpoint fails, give OpenCode the output and the module spec. Ask it to repair the implementation while retaining the supplied tests, UI, and interfaces. Run the checkpoint again before proceeding.
