# Module 60: Run the factory and resume saved work

## Need

The participant can invoke every stage. Now let the factory carry one request through the stages, and resume after a controlled stop without paying for another coding attempt.

## Implement

Retain earlier modules. Add `run REQUEST_FILE`, `recover RUN_ID`, and `resume RUN_ID` to `factory.py`.

`run` calls the worker exactly once; the worker's own attempt budget applies inside that call. On worker failure, stop before recording. On success, record the committed candidate with that worker's evidence, print its ID, then carry that ID through review, judge, and decide. Stop at the first failed stage. Keep all worker logs, attempts, and evidence. A rework task produced by the judge is a new request that the participant starts deliberately.

Add a fault switch: when `FACTORY_STOP_AFTER_SAVE=1`, `record` prints its new ID and returns nonzero immediately after the atomic state save. `run` must stop there too. This is a controlled stop at the save boundary, not a simulation of every possible host failure.

`recover` validates the saved identity, the recorded check evidence, and every later stage present, in order, and confirms that the candidate Git object still exists. Print the same ID, and name the first stage whose evidence is missing or invalid on stderr. Do not start a worker, create another run, replace the candidate, or alter the saved identity.

`resume` validates recovery, then runs review, judge, and decide on the original ID, stopping on failure. Reuse complete valid evidence under the earlier modules' rules. Invalid or missing check evidence is terminal for the run: `resume` exits nonzero and the participant works the task again and records a new run. A repeated resume with unchanged evidence preserves the complete saved state, including top-level `status` equal to `decision.status`, and the existing check logs, votes, and judge object. It starts no agent. A saved `ready` decision returns zero; `needs-rework` and `needs-human` retain their terminal status and return nonzero. A failed or partial stage requires the repair procedure and a new record; resume does not erase evidence.

## Check

Run `uv run tests/checkpoint.py 60`. It includes all earlier checks and exercises a complete local-substitute run, a stopped save, recovery, resume, worker failures, invalid check evidence stopping resume, and repeated resume without extra model calls.

Then set the policy base to the accepted Diagram Audit revision, and run the next request with the fault switch from `uv run factory-ui` (`g`). Press `R` to recover and `s` to resume that same run. The UI shows which stages were reused and which ran; compare the candidate ID, worker attempts, application behavior, check logs, three votes, quorum, judge, and decision. Retain the observed outcome.
