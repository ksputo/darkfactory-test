"""Pure functions from typed state to Rich text. No I/O, no decisions."""

from __future__ import annotations

from rich.text import Text

from .model import (
    AppStatus,
    CheckSource,
    Config,
    KeySpec,
    KeyState,
    RunKind,
    RunView,
    Stage,
    StageId,
    TaskRef,
    Token,
    VoteDecision,
)

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

TOKEN_STYLE = {
    Token.DARK: "dim",
    Token.IDLE: "",
    Token.BLOCKED: "yellow",
    Token.LIVE: "bold cyan",
    Token.PROVEN: "green",
    Token.FAILED: "bold red",
}


def glyph(token: Token, frame: int = 0) -> str:
    return SPINNER[frame % len(SPINNER)] if token is Token.LIVE else token.glyph


def styled(text: str, token: Token) -> Text:
    return Text(text, style=TOKEN_STYLE[token])


def fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 1, 1)] + "…"


def box_text(stage: Stage, frame: int = 0, elapsed: float | None = None, width: int = 40) -> Text:
    """Body of one pipeline box: token line, summary or reason, then sub-cells."""
    out = Text(no_wrap=False, overflow="fold")
    label = stage.headline or stage.token.value
    if stage.token is Token.LIVE and elapsed is not None:
        label = f"live {elapsed:.0f}s"
    out.append(f"{glyph(stage.token, frame)} {label}\n", TOKEN_STYLE[stage.token])
    if stage.token in (Token.DARK, Token.BLOCKED):
        parts = [stage.reason]
    elif stage.token is Token.FAILED:
        parts = [stage.summary, stage.reason]
    else:
        parts = [stage.summary]
    body = "\n".join(part for part in parts if part)
    if body:
        out.append(body + "\n", "dim" if stage.token is Token.DARK else "")
    if stage.attempts:
        out.append("try ", "dim")
        for index, cell in enumerate(stage.attempts):
            out.append(f"{glyph(cell.token)}{cell.name}", TOKEN_STYLE[cell.token])
            out.append(" " if index < len(stage.attempts) - 1 else "\n")
    for cell in stage.cells:
        out.append(f"{glyph(cell.token)} {cell.name}\n", TOKEN_STYLE[cell.token])
        if stage.id is StageId.PANEL:
            out.append(f"  {cell.detail}\n", "dim")
            out.append(fit(f"  {cell.extra}", width) + "\n", "dim")
    out.rstrip()
    return out


def key_hint(spec: KeySpec, state: KeyState) -> Text:
    if state.token is Token.DARK:
        return Text("")
    if state.token is Token.BLOCKED:
        return Text(f"🔒 {spec.key}", style="dim yellow")
    if state.token is Token.LIVE:
        return Text(f"{spec.key}", style="bold cyan")
    return Text(f"[{spec.key}]", style="bold")


def header_text(config: Config, app: AppStatus, problem: str) -> Text:
    out = Text(no_wrap=True, overflow="ellipsis")
    out.append("Lab    ", "dim").append(f"{config.lab}\n")
    out.append("App    ", "dim")
    if app.problem:
        out.append(f"({app.problem})  ", "yellow")
    else:
        out.append(f"@ {app.head or '?'}  ")
        out.append("dirty" if app.dirty else "clean", "yellow" if app.dirty else "green")
        out.append("  ")
    out.append(f"{app.path}\n")
    out.append("Model  ", "dim").append(config.model)
    if problem:
        out.append(f"   {problem}", "yellow")
    return out


def keybar_text(keys: dict[str, KeyState], specs: tuple[KeySpec, ...]) -> Text:
    out = Text(no_wrap=False)
    for spec in specs:
        state = keys[spec.key]
        if state.token is Token.DARK:
            continue
        style = {Token.BLOCKED: "dim yellow", Token.LIVE: "bold cyan"}.get(state.token, "bold")
        lock = "🔒" if state.token is Token.BLOCKED else ""
        out.append(f"{lock}{spec.key}", style)
        out.append(f" {spec.label}  ", "dim" if state.token is Token.BLOCKED else "")
    out.append("\n")
    for key, label in (("[ ]", "run"), ("←→", "stage"), ("↑↓", "task"), ("⏎", "preview"), ("l", "log"), ("q", "quit")):
        out.append(key, "bold").append(f" {label}  ")
    return out


def entries_text(entries: list[tuple[Token, str, str]], selected: int, height: int, empty: str) -> Text:
    """A windowed list. Each entry is (token, label, suffix)."""
    out = Text(no_wrap=True, overflow="ellipsis")
    if not entries:
        out.append(empty, "dim")
        return out
    start = max(0, min(selected - height // 2, len(entries) - height))
    for index in range(start, min(len(entries), start + height)):
        token, label, suffix = entries[index]
        marker = "▸" if index == selected else " "
        out.append(f"{marker} ", "bold" if index == selected else "")
        out.append(f"{glyph(token)} ", TOKEN_STYLE[token])
        out.append(label, "bold" if index == selected else "")
        if suffix:
            out.append(f" {suffix}", "dim")
        if index < min(len(entries), start + height) - 1:
            out.append("\n")
    return out


def _kv(out: Text, key: str, value: str) -> None:
    out.append(f"{key}: ", "dim")
    out.append(f"{value}\n")


def _title(out: Text, stage: Stage) -> None:
    out.append(f"{glyph(stage.token)} {stage.id.title}  ", TOKEN_STYLE[stage.token] + " bold")
    out.append(f"{stage.headline or stage.token.value}\n", TOKEN_STYLE[stage.token])
    if stage.reason:
        out.append(f"{stage.reason}\n", TOKEN_STYLE[stage.token])


def _decision_style(decision: VoteDecision) -> str:
    return "green" if decision is VoteDecision.APPROVE else "bold red"


def evidence_text(stage: Stage, run: RunView | None, task: tuple[TaskRef, str] | None) -> Text:
    out = Text()
    _title(out, stage)
    if stage.id is StageId.TASK:
        out.append("\n")
        if task is None:
            out.append("No tasks/*.md files.", "dim")
            return out
        ref, body = task
        out.append(f"tasks/{ref.name}.md", "bold")
        out.append("  (rework task)\n\n" if ref.rework else "\n\n", "yellow")
        out.append(body)
        return out
    if run is None:
        out.append("\nNo run selected.", "dim")
        return out
    out.append(f"run {run.run_id}", "bold").append(f"  ({run.kind.value})\n\n", "dim")
    {
        StageId.WORKER: _worker_evidence,
        StageId.PANEL: _panel_evidence,
        StageId.QUORUM: _quorum_evidence,
        StageId.JUDGE: _judge_evidence,
        StageId.POLICY: _policy_evidence,
    }[stage.id](out, run)
    return out


def _worker_evidence(out: Text, run: RunView) -> None:
    worker = run.worker
    if worker is None and run.identity is None:
        out.append("No worker.json or state.json in this run.", "dim")
        return
    if worker is not None and worker.attempts:
        out.append("attempts\n", "bold")
        for attempt in worker.attempts:
            token = Token.PROVEN if attempt.passed else Token.FAILED
            outcome = f"failed: {', '.join(attempt.failed)}" if attempt.failed else "passed"
            out.append(
                f"{glyph(token)} {attempt.attempt}  {attempt.candidate_revision[:7] or '(none)':<8} "
                f"checker_exit {attempt.checker_exit}  {outcome}\n",
                TOKEN_STYLE[token],
            )
        if run.last_brief is not None:
            _kv(out, "last brief", f"{run.last_brief.relative_to(run.path)}  (l opens it when the worker failed)")
        out.append("\n")
    _check_evidence(out, run)
    out.append("\n")
    if worker is not None:
        out.append("worker.json\n", "bold")
        _kv(out, "  task", worker.task)
        _kv(out, "  base_revision", worker.base_revision)
        _kv(out, "  candidate_revision", worker.candidate_revision or "(none)")
        _kv(out, "  exit", str(worker.exit))
        _kv(out, "  model", worker.model)
        _kv(out, "  logs/worker.log", "present" if worker.log_present else "missing")
        out.append("\n")
    if run.identity is not None:
        identity = run.identity
        out.append("state.json\n", "bold")
        _kv(out, "  status", identity.status)
        _kv(out, "  base_revision", identity.base_revision)
        _kv(out, "  candidate_revision", identity.candidate_revision)
        _kv(out, "  changed_paths", ", ".join(identity.changed_paths) or "(none)")
        for key, value in identity.hashes:
            _kv(out, f"  {key}", value)
        for key, value in identity.policy:
            _kv(out, f"  policy.{key}", value)


def _check_evidence(out: Text, run: RunView) -> None:
    out.append("final attempt: logs/NAME.exit, size of logs/NAME.log\n", "bold")
    for cell in run.check.cells:
        if cell.error:
            out.append(f"✘ {cell.name:<14} {cell.error}\n", "bold red")
            continue
        if cell.exit is None:
            out.append(f"○ {cell.name:<14} no exit file\n", "dim")
            continue
        token = Token.PROVEN if cell.exit == 0 else Token.FAILED
        size = f"{cell.log_bytes} B" if cell.log_bytes is not None else "no log"
        out.append(f"{glyph(token)} {cell.name:<14} exit {cell.exit:<3} {size}\n", TOKEN_STYLE[token])
    if run.check.source is CheckSource.NONE:
        out.append("no check object saved\n", "dim")
        return
    _kv(out, f"{run.check.source.value}.checker_exit", str(run.check.checker_exit))
    _kv(out, f"{run.check.source.value}.evidence_hash", run.check.evidence_hash)


def _panel_evidence(out: Text, run: RunView) -> None:
    for vote in run.votes:
        if vote is None:
            out.append("○ (no vote saved)\n\n", "dim")
            continue
        style = _decision_style(vote.decision)
        out.append(f"{vote.seat}  ", "bold").append(f"{vote.decision.value}\n", style)
        _kv(out, "  reason", vote.reason)
        for claim in vote.claims:
            out.append(f"  - {claim.path}: {claim.note}\n")
        out.append("\n")


def _quorum_evidence(out: Text, run: RunView) -> None:
    quorum = run.quorum
    if quorum is None:
        out.append("state.quorum is not saved yet.", "dim")
        return
    _kv(out, "required", str(quorum.required))
    _kv(out, "approvals", str(quorum.approvals))
    _kv(out, "passed", "yes" if quorum.passed else "no")
    out.append("\nvotes\n", "bold")
    for seat, decision in quorum.votes:
        out.append(f"  {seat}: ").append(f"{decision.value}\n", _decision_style(decision))


def _judge_evidence(out: Text, run: RunView) -> None:
    judge = run.judge
    if judge is None:
        out.append("state.judge is not saved yet.", "dim")
        return
    out.append("decision: ", "dim").append(f"{judge.decision.value}\n", _decision_style(judge.decision))
    _kv(out, "reason", judge.reason)
    if judge.brief is not None:
        brief = judge.brief
        out.append("\nbrief\n", "bold")
        _kv(out, "  failed_seats", ", ".join(brief.failed_seats) or "(none)")
        _kv(out, "  allowed_paths", ", ".join(brief.allowed_paths) or "(none)")
        _kv(out, "  budget_remaining", str(brief.budget_remaining))
        for excerpt in brief.excerpts:
            out.append(f"  > {excerpt}\n")
        _kv(out, "  next task", f"tasks/{run.rework_task}" if run.rework_task else "none written")
    if run.rework_brief:
        out.append("\nrework-brief.md\n", "bold").append(run.rework_brief)


def _policy_evidence(out: Text, run: RunView) -> None:
    decision = run.decision
    if decision is None:
        out.append("state.decision is not saved yet.", "dim")
        return
    out.append("status: ", "dim").append(f"{decision.status.value}\n", "green" if decision.status.value == "ready" else "bold red")
    _kv(out, "reason", decision.reason)
    for key, value in decision.hashes:
        _kv(out, key, value)
    if run.identity is not None:
        for key, value in run.identity.policy:
            _kv(out, f"policy.{key}", value)


def run_label(kind: RunKind) -> str:
    return {RunKind.RECORD: "record", RunKind.WORKER: "worker", RunKind.LOOP: "loop", RunKind.EMPTY: "empty"}[kind]
