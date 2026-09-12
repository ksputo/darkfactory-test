"""Typed view model for the factory UI.

Strings from the CLI and from saved files are decoded once, at the boundary
(`reader.py`, `backend.py`). Everything here is a display fact: the UI never
computes a hash, a vote, a quorum, or a verdict.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

DEFAULT_MODEL = "global.anthropic.claude-sonnet-5-5"
CHECK_NAMES = ("install", "typecheck", "code", "other", "build", "diagram-audit")
SEATS = ("intent", "failure-modes", "operability")
MAX_ATTEMPTS = 3


class Token(Enum):
    DARK = "dark"
    IDLE = "idle"
    BLOCKED = "blocked"
    LIVE = "live"
    PROVEN = "proven"
    FAILED = "failed"

    @property
    def glyph(self) -> str:
        return _GLYPHS[self]

    @property
    def runnable(self) -> bool:
        return self in (Token.IDLE, Token.PROVEN, Token.FAILED)


_GLYPHS = {
    Token.DARK: "○",
    Token.IDLE: "◇",
    Token.BLOCKED: "🔒",
    Token.LIVE: "⠋",
    Token.PROVEN: "✔",
    Token.FAILED: "✘",
}


class Command(Enum):
    WORK = "work"
    LOOP = "loop"
    RECORD = "record"
    SHOW = "show"
    REVIEW = "review"
    JUDGE = "judge"
    DECIDE = "decide"
    RECOVER = "recover"
    RESUME = "resume"
    RUN = "run"

    @property
    def module(self) -> int:
        return _MODULES[self]


_MODULES = {
    Command.WORK: 20,
    Command.LOOP: 20,
    Command.RECORD: 30,
    Command.SHOW: 30,
    Command.REVIEW: 40,
    Command.JUDGE: 40,
    Command.DECIDE: 50,
    Command.RECOVER: 60,
    Command.RESUME: 60,
    Command.RUN: 60,
}


class StageId(Enum):
    TASK = "task"
    WORKER = "worker"
    PANEL = "panel"
    QUORUM = "quorum"
    JUDGE = "judge"
    POLICY = "policy"

    @property
    def title(self) -> str:
        return self.value.capitalize()


PIPELINE = tuple(StageId)

STAGE_COMMAND = {
    StageId.WORKER: Command.WORK,
    StageId.PANEL: Command.REVIEW,
    StageId.QUORUM: Command.JUDGE,
    StageId.JUDGE: Command.JUDGE,
    StageId.POLICY: Command.DECIDE,
}


@dataclass(frozen=True)
class KeySpec:
    key: str
    command: Command
    stage: StageId | None
    label: str


KEYS = (
    KeySpec("w", Command.WORK, StageId.WORKER, "work"),
    KeySpec("v", Command.REVIEW, StageId.PANEL, "review"),
    KeySpec("j", Command.JUDGE, StageId.JUDGE, "judge"),
    KeySpec("d", Command.DECIDE, StageId.POLICY, "decide"),
    KeySpec("r", Command.RECORD, None, "record"),
    KeySpec("R", Command.RECOVER, None, "recover"),
    KeySpec("s", Command.RESUME, None, "resume"),
    KeySpec("g", Command.RUN, None, "run"),
)


@dataclass(frozen=True)
class Discovery:
    """The wired commands, read from `factory.py` with no arguments."""

    wired: frozenset[Command]
    problem: str = ""

    def is_wired(self, command: Command) -> bool:
        return command in self.wired

    @classmethod
    def parse(cls, stdout: str) -> Discovery:
        known = {command.value: command for command in Command}
        names = (line.strip() for line in stdout.splitlines())
        return cls(frozenset(known[name] for name in names if name in known))

    @classmethod
    def dark(cls, problem: str) -> Discovery:
        return cls(frozenset(), problem)


class ShowStatus(Enum):
    UNWIRED = "unwired"
    UNKNOWN = "unknown"
    OK = "ok"
    FAILED = "failed"


@dataclass(frozen=True)
class ShowResult:
    """Validity of one run, decoded from the exit code of `factory.py show RUN_ID`."""

    status: ShowStatus
    reason: str = ""


class RunKind(Enum):
    RECORD = "record"
    WORKER = "worker"
    LOOP = "loop"
    EMPTY = "empty"


class VoteDecision(Enum):
    APPROVE = "approve"
    REWORK = "rework"


class PolicyStatus(Enum):
    READY = "ready"
    NEEDS_REWORK = "needs-rework"
    NEEDS_HUMAN = "needs-human"


@dataclass(frozen=True)
class TaskRef:
    name: str
    path: Path

    @property
    def rework(self) -> bool:
        return self.name.startswith("rework-")


@dataclass(frozen=True)
class Identity:
    run_id: str
    status: str
    base_revision: str
    candidate_revision: str
    changed_paths: tuple[str, ...]
    hashes: tuple[tuple[str, str], ...]
    policy: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Attempt:
    """One entry of `worker.json` `attempts`."""

    attempt: int
    candidate_revision: str
    checker_exit: int | None
    failed: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.checker_exit == 0 and not self.failed


@dataclass(frozen=True)
class WorkerInfo:
    task: str
    base_revision: str
    candidate_revision: str
    exit: int
    model: str
    log_present: bool
    attempts: tuple[Attempt, ...] = ()


@dataclass(frozen=True)
class CheckCell:
    name: str
    exit: int | None
    log_bytes: int | None
    error: str = ""


class CheckSource(Enum):
    """Where the check object came from: the run's state, or a worker directory's file."""

    STATE = "state.check"
    FILE = "check.json"
    NONE = ""


@dataclass(frozen=True)
class CheckInfo:
    """The final attempt's six exits from `logs/` and the saved check object."""

    cells: tuple[CheckCell, ...]
    source: CheckSource
    checker_exit: int | None
    evidence_hash: str


@dataclass(frozen=True)
class Claim:
    path: str
    note: str


@dataclass(frozen=True)
class Vote:
    seat: str
    decision: VoteDecision
    reason: str
    claims: tuple[Claim, ...]


@dataclass(frozen=True)
class Quorum:
    required: int
    approvals: int
    votes: tuple[tuple[str, VoteDecision], ...]
    passed: bool


@dataclass(frozen=True)
class Brief:
    failed_seats: tuple[str, ...]
    excerpts: tuple[str, ...]
    allowed_paths: tuple[str, ...]
    budget_remaining: int | None


@dataclass(frozen=True)
class Judge:
    decision: VoteDecision
    reason: str
    brief: Brief | None


@dataclass(frozen=True)
class Decision:
    status: PolicyStatus
    reason: str
    hashes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class RunView:
    """Everything the UI reads about one directory under `runs/`."""

    run_id: str
    kind: RunKind
    path: Path
    identity: Identity | None
    state_problem: str
    worker: WorkerInfo | None
    check: CheckInfo
    votes: tuple[Vote | None, ...]
    reviews_recorded: bool
    quorum: Quorum | None
    judge: Judge | None
    decision: Decision | None
    rework_brief: str
    rework_task: str
    worker_dir: Path
    last_brief: Path | None = None
    problems: dict[StageId, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RunRef:
    run_id: str
    path: Path
    mtime_ns: int


@dataclass(frozen=True)
class Cell:
    name: str
    token: Token
    detail: str = ""
    extra: str = ""


@dataclass(frozen=True)
class Stage:
    id: StageId
    token: Token
    summary: str = ""
    reason: str = ""
    cells: tuple[Cell, ...] = ()
    valid: bool = False
    headline: str = ""
    attempts: tuple[Cell, ...] = ()


@dataclass(frozen=True)
class KeyState:
    token: Token
    reason: str = ""


@dataclass(frozen=True)
class Pipeline:
    stages: tuple[Stage, ...]
    keys: dict[str, KeyState]

    def stage(self, stage_id: StageId) -> Stage:
        return next(stage for stage in self.stages if stage.id is stage_id)


@dataclass(frozen=True)
class AppStatus:
    path: Path
    head: str = ""
    revision: str = ""
    dirty: bool | None = None
    problem: str = ""


@dataclass(frozen=True)
class Config:
    lab: Path
    app: Path
    model: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str], cwd: Path) -> Config:
        lab = Path(environ.get("FACTORY_LAB_DIR") or cwd)
        home = environ.get("HOME", str(Path.home()))
        app = Path(environ.get("EXCALIDRAW_DIR") or Path(home) / "environment" / "excalidraw")
        return cls(lab=lab, app=app, model=environ.get("FACTORY_MODEL") or DEFAULT_MODEL)
