"""Map decoded facts to one visual token per stage.

Input is the discovery list, the exit status of `show`, and the files the factory
saved. Output is a display state. No verdict is computed here: `valid` means "the
factory saved this stage and `show` accepts it", which gates the next stage's key.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from .model import (
    KEYS,
    MAX_ATTEMPTS,
    PIPELINE,
    SEATS,
    STAGE_COMMAND,
    Cell,
    CheckSource,
    Command,
    Discovery,
    KeyState,
    Pipeline,
    PolicyStatus,
    RunKind,
    RunView,
    ShowResult,
    ShowStatus,
    Stage,
    StageId,
    TaskRef,
    Token,
    VoteDecision,
)


@dataclass(frozen=True)
class Inputs:
    discovery: Discovery
    tasks: tuple[TaskRef, ...]
    run: RunView | None
    show: ShowResult
    live: Command | None = None
    failures: Mapping[Command, str] | None = None
    selected_task: TaskRef | None = None
    head_worker: RunView | None = None


def short(revision: str) -> str:
    return revision[:7]


def dark(stage_id: StageId) -> Stage:
    return Stage(stage_id, Token.DARK, reason=f"Build this in module {STAGE_COMMAND[stage_id].module}")


@dataclass(frozen=True)
class Gate:
    ok: bool
    reason: str = ""


def verification_override(stage_id: StageId, show: ShowResult) -> Stage | None:
    """A saved stage only counts once `show` accepts the run."""
    if show.status is ShowStatus.FAILED:
        return Stage(stage_id, Token.FAILED, reason=f"show: {show.reason}")
    if show.status is ShowStatus.UNKNOWN:
        return Stage(stage_id, Token.BLOCKED, reason="verifying with show")
    if show.status is ShowStatus.UNWIRED:
        return Stage(stage_id, Token.BLOCKED, reason="show is not wired")
    return None


def pending(stage_id: StageId, gate: Gate, failure: str | None) -> Stage:
    if not gate.ok:
        return Stage(stage_id, Token.BLOCKED, reason=gate.reason)
    if failure:
        return Stage(stage_id, Token.FAILED, reason=failure)
    return Stage(stage_id, Token.IDLE)


def effective_show(i: Inputs) -> ShowResult:
    if i.run is not None and i.run.state_problem:
        return ShowResult(ShowStatus.FAILED, i.run.state_problem)
    return i.show


def attempt_cells(run: RunView) -> tuple[Cell, ...]:
    attempts = run.worker.attempts if run.worker is not None else ()
    done = tuple(
        Cell(str(attempt.attempt), Token.PROVEN if attempt.passed else Token.FAILED, ", ".join(attempt.failed))
        for attempt in attempts
    )
    return done + tuple(Cell(str(number), Token.DARK) for number in range(len(done) + 1, MAX_ATTEMPTS + 1))


def check_cells(run: RunView) -> tuple[Cell, ...]:
    cells = []
    for cell in run.check.cells:
        if cell.error:
            cells.append(Cell(cell.name, Token.FAILED, cell.error))
        elif cell.exit is None:
            cells.append(Cell(cell.name, Token.DARK, "not run"))
        else:
            cells.append(Cell(cell.name, Token.PROVEN if cell.exit == 0 else Token.FAILED, f"exit {cell.exit}"))
    return tuple(cells)


def worker_failure(run: RunView) -> str:
    """First reason the saved worker evidence does not show a passing final attempt, or ''."""
    worker = run.worker
    if worker is not None:
        last = worker.attempts[-1] if worker.attempts else None
        if worker.exit != 0:
            if last is not None and last.failed:
                return f"{len(worker.attempts)} of {MAX_ATTEMPTS} attempts, failed: {', '.join(last.failed)}"
            return f"worker exit {worker.exit}"
        if not worker.candidate_revision or worker.candidate_revision == worker.base_revision:
            return "no new commit"
        if not worker.log_present:
            return "missing logs/worker.log"
        if last is not None and last.failed:
            return f"attempt {last.attempt} failed: {', '.join(last.failed)}"
    for cell in run.check.cells:
        if cell.error:
            return cell.error
        if cell.exit is None:
            return f"missing logs/{cell.name}.exit"
        if cell.exit != 0:
            return f"{cell.name} exit {cell.exit}"
    if run.check.source is CheckSource.NONE:
        return "missing state.check" if run.kind is RunKind.RECORD else "missing check.json"
    if run.check.checker_exit != 0:
        return f"checker exit {run.check.checker_exit}"
    return ""


def worker_stage(i: Inputs, show: ShowResult, has_state: bool) -> Stage:
    if not i.discovery.is_wired(Command.WORK):
        return dark(StageId.WORKER)
    run = i.run
    if run is not None and run.problems.get(StageId.WORKER):
        return Stage(StageId.WORKER, Token.FAILED, reason=run.problems[StageId.WORKER])
    if run is None or (run.worker is None and not has_state):
        gate = Gate(bool(i.tasks), "needs a task in tasks/")
        return pending(StageId.WORKER, gate, (i.failures or {}).get(Command.WORK))
    if identity := run.identity:
        candidate = identity.candidate_revision
    else:
        candidate = run.worker.candidate_revision if run.worker else ""
    shown = Stage(
        StageId.WORKER,
        Token.PROVEN,
        summary=f"{run.run_id}\n{short(candidate)}" if candidate else run.run_id,
        attempts=attempt_cells(run),
        cells=check_cells(run),
    )
    override = verification_override(StageId.WORKER, show) if has_state else None
    if override is not None and override.token is Token.FAILED:
        return replace(shown, token=Token.FAILED, reason=override.reason)
    failure = worker_failure(run)
    if failure:
        return replace(shown, token=Token.FAILED, reason=failure)
    if override is not None:
        return replace(shown, token=override.token, reason=override.reason)
    return replace(shown, valid=True)


def show_reason(show: ShowResult) -> str:
    return f"show: {show.reason}" if show.status is ShowStatus.FAILED else ""


def check_gate(run: RunView | None, show: ShowResult, worker: Stage) -> Gate:
    """The panel needs a recorded run that `show` accepts and whose check evidence passed."""
    if run is None or run.kind is not RunKind.RECORD:
        return Gate(False, "needs record")
    override = verification_override(StageId.PANEL, show)
    if override is not None:
        return Gate(False, override.reason)
    if not worker.valid:
        return Gate(False, "needs passing check evidence")
    return Gate(True)


def panel_stage(i: Inputs, show: ShowResult, has_state: bool, worker: Stage) -> Stage:
    if not i.discovery.is_wired(Command.REVIEW):
        return dark(StageId.PANEL)
    failure = (i.failures or {}).get(Command.REVIEW)
    run = i.run
    gate = check_gate(run, show, worker)
    if not has_state or (not any(run.votes) and not run.reviews_recorded):
        return pending(StageId.PANEL, gate, failure)
    if run.problems.get(StageId.PANEL):
        return Stage(StageId.PANEL, Token.FAILED, reason=run.problems[StageId.PANEL])
    cells = tuple(
        Cell(
            seat,
            Token.PROVEN if vote.decision is VoteDecision.APPROVE else Token.FAILED,
            vote.decision.value,
            vote.claims[0].path if vote.claims else "no claims",
        )
        if vote
        else Cell(seat, Token.FAILED if run.reviews_recorded else Token.DARK, "missing" if run.reviews_recorded else "not run")
        for seat, vote in zip(SEATS, run.votes, strict=True)
    )
    override = verification_override(StageId.PANEL, show)
    if override is not None and override.token is Token.FAILED:
        return replace(override, cells=cells)
    if run.reviews_recorded and all(run.votes):
        return replace(override, cells=cells) if override else Stage(
            StageId.PANEL, Token.PROVEN, summary="3 votes saved", cells=cells, valid=True
        )
    if run.reviews_recorded:
        missing = next(seat for seat, vote in zip(SEATS, run.votes, strict=True) if vote is None)
        return Stage(StageId.PANEL, Token.FAILED, reason=f"missing reviews/{missing}.json", cells=cells)
    done = sum(1 for vote in run.votes if vote)
    return Stage(StageId.PANEL, Token.IDLE, summary=f"partial {done} of {len(SEATS)}", cells=cells)


def quorum_stage(i: Inputs, show: ShowResult, has_state: bool, panel: Stage) -> Stage:
    if not i.discovery.is_wired(Command.JUDGE):
        return dark(StageId.QUORUM)
    run = i.run
    if run is not None and run.problems.get(StageId.QUORUM):
        return Stage(StageId.QUORUM, Token.FAILED, reason=run.problems[StageId.QUORUM])
    if not has_state or run.quorum is None:
        return pending(StageId.QUORUM, Gate(panel.valid, show_reason(show) or "needs panel"), None)
    override = verification_override(StageId.QUORUM, show)
    if override is not None:
        return override
    quorum = run.quorum
    summary = f"{'passed' if quorum.passed else 'failed'}\nrequired {quorum.required}"
    return Stage(
        StageId.QUORUM,
        Token.PROVEN if quorum.passed else Token.FAILED,
        headline=f"{quorum.approvals} of {len(quorum.votes)}",
        summary=summary,
        valid=True,
    )


def judge_stage(i: Inputs, show: ShowResult, has_state: bool, panel: Stage) -> Stage:
    if not i.discovery.is_wired(Command.JUDGE):
        return dark(StageId.JUDGE)
    run = i.run
    if run is not None and run.problems.get(StageId.JUDGE):
        return Stage(StageId.JUDGE, Token.FAILED, reason=run.problems[StageId.JUDGE])
    if not has_state or run.judge is None:
        return pending(
            StageId.JUDGE, Gate(panel.valid, show_reason(show) or "needs panel"), (i.failures or {}).get(Command.JUDGE)
        )
    override = verification_override(StageId.JUDGE, show)
    if override is not None:
        return override
    judge = run.judge
    if judge.decision is VoteDecision.APPROVE:
        return Stage(StageId.JUDGE, Token.PROVEN, headline="approve", valid=True)
    lines = []
    if judge.brief is not None:
        lines.append("brief: " + (", ".join(judge.brief.failed_seats) or "no seats listed"))
    lines += ["task file:", run.rework_task] if run.rework_task else ["no task file"]
    return Stage(StageId.JUDGE, Token.FAILED, headline="rework", summary="\n".join(lines), valid=True)


def policy_stage(i: Inputs, show: ShowResult, has_state: bool, judge: Stage) -> Stage:
    if not i.discovery.is_wired(Command.DECIDE):
        return dark(StageId.POLICY)
    run = i.run
    if run is not None and run.problems.get(StageId.POLICY):
        return Stage(StageId.POLICY, Token.FAILED, reason=run.problems[StageId.POLICY])
    if not has_state or run.decision is None:
        return pending(
            StageId.POLICY, Gate(judge.valid, show_reason(show) or "needs judge"), (i.failures or {}).get(Command.DECIDE)
        )
    override = verification_override(StageId.POLICY, show)
    if override is not None:
        return override
    status = run.decision.status
    return Stage(
        StageId.POLICY,
        Token.PROVEN if status is PolicyStatus.READY else Token.FAILED,
        headline=status.value,
        valid=True,
    )


def task_stage(i: Inputs) -> Stage:
    count = len(i.tasks)
    summary = f"{count} task{'s' if count != 1 else ''}"
    if i.selected_task is not None:
        summary += f"\n{i.selected_task.name}" + ("\n(rework)" if i.selected_task.rework else "")
    return Stage(StageId.TASK, Token.IDLE, summary=summary)


STATE_STAGES = (StageId.PANEL, StageId.JUDGE, StageId.POLICY)


def run_token(run: RunView, show: ShowResult) -> Token:
    """Color of one entry in the run selector."""
    if run.kind is RunKind.RECORD:
        if run.state_problem:
            return Token.FAILED
        return {
            ShowStatus.FAILED: Token.FAILED,
            ShowStatus.OK: Token.PROVEN,
            ShowStatus.UNKNOWN: Token.BLOCKED,
            ShowStatus.UNWIRED: Token.IDLE,
        }[show.status]
    if run.problems.get(StageId.WORKER):
        return Token.FAILED
    if run.worker is None:
        return Token.IDLE
    return Token.FAILED if worker_failure(run) else Token.PROVEN


def live_stage(command: Command, stages: Mapping[StageId, Stage]) -> StageId | None:
    direct = {
        Command.WORK: StageId.WORKER,
        Command.LOOP: StageId.WORKER,
        Command.RUN: StageId.WORKER,
        Command.REVIEW: StageId.PANEL,
        Command.JUDGE: StageId.JUDGE,
        Command.DECIDE: StageId.POLICY,
    }
    if command in direct:
        return direct[command]
    if command is Command.RESUME:
        return next((sid for sid in STATE_STAGES if not stages[sid].valid), StageId.POLICY)
    return None


def evaluate(i: Inputs) -> Pipeline:
    show = effective_show(i)
    has_state = i.run is not None and i.run.kind is RunKind.RECORD
    stages = {StageId.TASK: task_stage(i)}
    stages[StageId.WORKER] = worker_stage(i, show, has_state)
    stages[StageId.PANEL] = panel_stage(i, show, has_state, stages[StageId.WORKER])
    stages[StageId.QUORUM] = quorum_stage(i, show, has_state, stages[StageId.PANEL])
    stages[StageId.JUDGE] = judge_stage(i, show, has_state, stages[StageId.PANEL])
    stages[StageId.POLICY] = policy_stage(i, show, has_state, stages[StageId.JUDGE])

    live_id = live_stage(i.live, stages) if i.live is not None else None
    if live_id is not None:
        stages[live_id] = replace(stages[live_id], token=Token.LIVE, reason="")

    return Pipeline(tuple(stages[sid] for sid in PIPELINE), key_states(i, stages, has_state, live_id))


def record_key(i: Inputs) -> KeyState:
    """`r` records the latest `runs/worker-*` whose candidate is the application HEAD."""
    source = i.head_worker
    if source is None:
        return KeyState(Token.BLOCKED, "needs a worker whose candidate is HEAD")
    if source.worker is not None and source.worker.exit != 0:
        return KeyState(Token.BLOCKED, f"{source.run_id} exit {source.worker.exit}")
    return KeyState(Token.IDLE)


def key_states(i: Inputs, stages: Mapping[StageId, Stage], has_state: bool, live_id: StageId | None) -> dict[str, KeyState]:
    keys: dict[str, KeyState] = {}
    for spec in KEYS:
        if not i.discovery.is_wired(spec.command):
            keys[spec.key] = KeyState(Token.DARK, f"Build this in module {spec.command.module}")
        elif i.live is spec.command or (i.live is not None and spec.stage is not None and spec.stage is live_id):
            keys[spec.key] = KeyState(Token.LIVE)
        elif i.live is not None:
            keys[spec.key] = KeyState(Token.BLOCKED, f"{i.live.value} is running")
        elif spec.stage is not None:
            stage = stages[spec.stage]
            keys[spec.key] = KeyState(Token.BLOCKED if stage.token is Token.BLOCKED else Token.IDLE, stage.reason)
        elif spec.command is Command.RECORD:
            keys[spec.key] = record_key(i)
        elif spec.command in (Command.RECOVER, Command.RESUME):
            keys[spec.key] = KeyState(Token.IDLE) if has_state else KeyState(Token.BLOCKED, "needs record")
        else:
            keys[spec.key] = KeyState(Token.IDLE) if i.tasks else KeyState(Token.BLOCKED, "needs a task in tasks/")
    return keys
