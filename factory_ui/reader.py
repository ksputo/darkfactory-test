"""Read-only decoding of the files the factory saves. Nothing here writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import (
    CHECK_NAMES,
    SEATS,
    Attempt,
    Brief,
    CheckCell,
    CheckInfo,
    CheckSource,
    Claim,
    Decision,
    Identity,
    Judge,
    PolicyStatus,
    Quorum,
    RunKind,
    RunRef,
    RunView,
    StageId,
    TaskRef,
    Vote,
    VoteDecision,
    WorkerInfo,
)

IDENTITY_HASHES = ("request_hash", "policy_hash", "record_hash")
DECISION_HASHES = ("evidence_hash", "review_hash", "judge_hash", "policy_hash", "decision_hash")


class DecodeError(ValueError):
    pass


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DecodeError(f"{where}: expected an object, got {type(value).__name__}")
    return value


def _text(data: dict[str, Any], key: str, where: str, required: bool = False) -> str:
    value = data.get(key)
    if value is None:
        if required:
            raise DecodeError(f"{where}: missing '{key}'")
        return ""
    if not isinstance(value, str):
        raise DecodeError(f"{where}: '{key}' must be a string, got {type(value).__name__}")
    return value


def _integer(data: dict[str, Any], key: str, where: str, required: bool = False) -> int | None:
    value = data.get(key)
    if value is None:
        if required:
            raise DecodeError(f"{where}: missing '{key}'")
        return None
    if type(value) is not int:
        raise DecodeError(f"{where}: '{key}' must be an integer, got {value!r}")
    return value


def _strings(data: dict[str, Any], key: str, where: str) -> tuple[str, ...]:
    value = data.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise DecodeError(f"{where}: '{key}' must be a list of strings")
    return tuple(value)


def _decision(data: dict[str, Any], where: str) -> VoteDecision:
    raw = _text(data, "decision", where, required=True)
    try:
        return VoteDecision(raw)
    except ValueError:
        raise DecodeError(f"{where}: unexpected decision {raw!r}") from None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except OSError as error:
        raise DecodeError(f"{path.name}: {error}") from error
    except json.JSONDecodeError as error:
        raise DecodeError(f"{path.name}: invalid JSON ({error})") from error


def decode_attempt(data: Any, index: int) -> Attempt:
    where = f"worker.json attempts[{index}]"
    data = _object(data, where)
    return Attempt(
        attempt=_integer(data, "attempt", where, required=True) or 0,
        candidate_revision=_text(data, "candidate_revision", where),
        checker_exit=_integer(data, "checker_exit", where),
        failed=_strings(data, "failed", where),
    )


def decode_worker(data: Any, log_present: bool) -> WorkerInfo:
    where = "worker.json"
    data = _object(data, where)
    attempts = data.get("attempts") or []
    if not isinstance(attempts, list):
        raise DecodeError(f"{where}: 'attempts' must be a list")
    return WorkerInfo(
        task=_text(data, "task", where),
        base_revision=_text(data, "base_revision", where),
        candidate_revision=_text(data, "candidate_revision", where),
        exit=_integer(data, "exit", where, required=True) or 0,
        model=_text(data, "model", where),
        log_present=log_present,
        attempts=tuple(decode_attempt(entry, index) for index, entry in enumerate(attempts)),
    )


def decode_vote(data: Any, seat: str) -> Vote:
    where = f"reviews/{seat}.json"
    data = _object(data, where)
    claims = []
    for claim in data.get("claims") or []:
        claim = _object(claim, f"{where} claims")
        claims.append(Claim(_text(claim, "path", where), _text(claim, "note", where)))
    return Vote(seat, _decision(data, where), _text(data, "reason", where), tuple(claims))


def decode_quorum(data: Any) -> Quorum:
    where = "state.quorum"
    data = _object(data, where)
    votes = _object(data.get("votes") or {}, f"{where}.votes")
    passed = data.get("passed")
    if type(passed) is not bool:
        raise DecodeError(f"{where}: 'passed' must be true or false, got {passed!r}")
    ordered = []
    for seat, raw in votes.items():
        try:
            ordered.append((seat, VoteDecision(raw)))
        except ValueError:
            raise DecodeError(f"{where}.votes.{seat}: unexpected decision {raw!r}") from None
    return Quorum(
        required=_integer(data, "required", where, required=True) or 0,
        approvals=_integer(data, "approvals", where, required=True) or 0,
        votes=tuple(ordered),
        passed=passed,
    )


def decode_judge(data: Any) -> Judge:
    where = "state.judge"
    data = _object(data, where)
    raw_brief = data.get("brief")
    brief = None
    if raw_brief is not None:
        raw_brief = _object(raw_brief, f"{where}.brief")
        brief = Brief(
            failed_seats=_strings(raw_brief, "failed_seats", f"{where}.brief"),
            excerpts=_strings(raw_brief, "excerpts", f"{where}.brief"),
            allowed_paths=_strings(raw_brief, "allowed_paths", f"{where}.brief"),
            budget_remaining=_integer(raw_brief, "budget_remaining", f"{where}.brief"),
        )
    return Judge(_decision(data, where), _text(data, "reason", where), brief)


def decode_decision(data: Any) -> Decision:
    where = "state.decision"
    data = _object(data, where)
    raw = _text(data, "status", where, required=True)
    try:
        status = PolicyStatus(raw)
    except ValueError:
        raise DecodeError(f"{where}: unexpected status {raw!r}") from None
    hashes = tuple((key, _text(data, key, where)) for key in DECISION_HASHES if data.get(key))
    return Decision(status, _text(data, "reason", where), hashes)


def decode_identity(state: dict[str, Any]) -> Identity:
    where = "state.json"
    policy = state.get("policy")
    policy_items = (
        tuple((str(key), str(value)) for key, value in policy.items()) if isinstance(policy, dict) else ()
    )
    return Identity(
        run_id=_text(state, "run_id", where),
        status=_text(state, "status", where),
        base_revision=_text(state, "base_revision", where),
        candidate_revision=_text(state, "candidate_revision", where),
        changed_paths=_strings(state, "changed_paths", where),
        hashes=tuple((key, _text(state, key, where)) for key in IDENTITY_HASHES if state.get(key)),
        policy=policy_items,
    )


def read_check(worker_dir: Path, saved: Any, source: CheckSource) -> CheckInfo:
    """Six exits of the final attempt from `logs/`, plus the saved check object when there is one."""
    logs = worker_dir / "logs"
    cells = []
    for name in CHECK_NAMES:
        exit_file, log_file = logs / f"{name}.exit", logs / f"{name}.log"
        log_bytes = log_file.stat().st_size if log_file.is_file() else None
        if not exit_file.is_file():
            cells.append(CheckCell(name, None, log_bytes))
            continue
        raw = exit_file.read_text().strip()
        try:
            cells.append(CheckCell(name, int(raw), log_bytes))
        except ValueError:
            cells.append(CheckCell(name, None, log_bytes, error=f"logs/{name}.exit is not an integer: {raw!r}"))
    if not isinstance(saved, dict):
        return CheckInfo(tuple(cells), CheckSource.NONE, checker_exit=None, evidence_hash="")
    checker_exit = saved.get("checker_exit")
    return CheckInfo(
        tuple(cells),
        source,
        checker_exit=checker_exit if type(checker_exit) is int else None,
        evidence_hash=str(saved.get("evidence_hash") or ""),
    )


def last_brief(worker_dir: Path) -> Path | None:
    """`attempts/N/brief.md` with the highest N."""
    briefs = [path for path in worker_dir.glob("attempts/*/brief.md") if path.parent.name.isdigit()]
    return max(briefs, key=lambda path: int(path.parent.name), default=None)


def run_signature(lab: Path, run_id: str) -> tuple[tuple[str, int, int], ...]:
    """Stat the files the UI reads, so unchanged runs are not re-read or re-validated."""
    root = lab / "runs" / run_id
    patterns = (
        "state.json",
        "worker.json",
        "check.json",
        "request.md",
        "rework-brief.md",
        "logs/*",
        "reviews/*",
        "attempts/*/brief.md",
        "*/worker.json",
        "*/check.json",
        "*/logs/*",
        "*/attempts/*/brief.md",
    )
    seen = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            try:
                stat = path.stat()
            except OSError:
                continue
            seen.append((str(path.relative_to(root)), stat.st_mtime_ns, stat.st_size))
    return tuple(seen)


def _newest_child_worker(run_dir: Path) -> Path | None:
    children = [child for child in run_dir.iterdir() if (child / "worker.json").is_file()]
    return max(children, key=lambda child: (child / "worker.json").stat().st_mtime_ns, default=None)


def read_run(lab: Path, run_id: str) -> RunView:
    run_dir = lab / "runs" / run_id
    problems: dict[StageId, str] = {}
    state: dict[str, Any] = {}
    state_problem = ""
    identity = None
    state_file = run_dir / "state.json"
    kind = RunKind.EMPTY
    worker_dir = run_dir

    if state_file.is_file():
        kind = RunKind.RECORD
        try:
            state = _object(_load_json(state_file), "state.json")
            identity = decode_identity(state)
        except DecodeError as error:
            state, state_problem = {}, str(error)
    elif (run_dir / "worker.json").is_file():
        kind = RunKind.WORKER
    else:
        child = _newest_child_worker(run_dir) if run_dir.is_dir() else None
        if child is not None:
            kind, worker_dir = RunKind.LOOP, child

    worker = None
    if (worker_dir / "worker.json").is_file():
        try:
            worker = decode_worker(_load_json(worker_dir / "worker.json"), (worker_dir / "logs" / "worker.log").is_file())
        except DecodeError as error:
            problems[StageId.WORKER] = str(error)

    if kind is RunKind.RECORD:
        check = read_check(worker_dir, state.get("check"), CheckSource.STATE)
    else:
        saved = None
        if (worker_dir / "check.json").is_file():
            try:
                saved = _object(_load_json(worker_dir / "check.json"), "check.json")
            except DecodeError as error:
                problems.setdefault(StageId.WORKER, str(error))
        check = read_check(worker_dir, saved, CheckSource.FILE)

    votes: list[Vote | None] = []
    for seat in SEATS:
        vote_file = run_dir / "reviews" / f"{seat}.json"
        if not vote_file.is_file():
            votes.append(None)
            continue
        try:
            votes.append(decode_vote(_load_json(vote_file), seat))
        except DecodeError as error:
            votes.append(None)
            problems.setdefault(StageId.PANEL, str(error))
    reviews = state.get("reviews")
    reviews_recorded = isinstance(reviews, dict) and all(seat in reviews for seat in SEATS)

    def section(stage: StageId, key: str, decode):
        if state.get(key) is None:
            return None
        try:
            return decode(state[key])
        except DecodeError as error:
            problems[stage] = str(error)
            return None

    quorum = section(StageId.QUORUM, "quorum", decode_quorum)
    judge = section(StageId.JUDGE, "judge", decode_judge)
    decision = section(StageId.POLICY, "decision", decode_decision)

    brief_file = run_dir / "rework-brief.md"
    rework_name = f"rework-{run_id}.md"
    return RunView(
        run_id=run_id,
        kind=kind,
        path=run_dir,
        identity=identity,
        state_problem=state_problem,
        worker=worker,
        check=check,
        votes=tuple(votes),
        reviews_recorded=reviews_recorded,
        quorum=quorum,
        judge=judge,
        decision=decision,
        rework_brief=brief_file.read_text(errors="replace") if brief_file.is_file() else "",
        rework_task=rework_name if (lab / "tasks" / rework_name).is_file() else "",
        worker_dir=worker_dir,
        last_brief=last_brief(worker_dir) if worker_dir.is_dir() else None,
        problems=problems,
    )


def list_runs(lab: Path) -> list[RunRef]:
    """`runs/*` newest first. A run is as new as its newest saved top-level file."""
    root = lab / "runs"
    if not root.is_dir():
        return []
    refs = []
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        stamps = [entry.stat().st_mtime_ns]
        stamps += [
            (entry / name).stat().st_mtime_ns for name in ("state.json", "worker.json") if (entry / name).is_file()
        ]
        refs.append(RunRef(entry.name, entry, max(stamps)))
    return sorted(refs, key=lambda ref: (ref.mtime_ns, ref.run_id), reverse=True)


def list_tasks(lab: Path) -> list[TaskRef]:
    root = lab / "tasks"
    if not root.is_dir():
        return []
    return [TaskRef(path.name.removesuffix(".md"), path) for path in sorted(root.glob("*.md"))]
