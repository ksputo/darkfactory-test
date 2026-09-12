"""Builders for lab directories used by the factory_ui tests.

The layout follows specs/interfaces.md: a worker directory holds the final attempt at
`logs/` and `check.json`, earlier failed attempts under `attempts/N/`, and `worker.json`.
`record` copies that evidence into the run directory and saves `state.check`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from factory_ui.model import CHECK_NAMES, SEATS

FAKE_FACTORY = Path(__file__).parent / "fixtures" / "fake_lab" / "factory.py"
BASE = "a" * 40
CANDIDATE = "b" * 40


def make_app_repo(path: Path) -> str:
    """Create a one-commit checkout and return its full HEAD revision."""
    path.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", str(path), "-c", "user.name=t", "-c", "user.email=t@example.com"]
    subprocess.run([*git, "init", "-q"], check=True)
    (path / "README.md").write_text("app\n")
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    return subprocess.run([*git, "log", "-1", "--format=%H"], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()


def write_check(directory: Path, exits: dict[str, int], checker_exit: int) -> None:
    logs = directory / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    for name, code in exits.items():
        (logs / f"{name}.exit").write_text(f"{code}\n")
        (logs / f"{name}.log").write_text(f"{name} output\n" * 3)
    check = {
        "proof": {"commands": [{"name": name, "exit": code} for name, code in exits.items()]},
        "evidence_hash": "4" * 64,
        "checker_exit": checker_exit,
    }
    (directory / "check.json").write_text(json.dumps(check))


def exits_failing(failed: Sequence[str]) -> dict[str, int]:
    return {name: (2 if name in failed else 0) for name in CHECK_NAMES}


class Lab:
    def __init__(self, root: Path) -> None:
        self.root = root
        (root / "tasks").mkdir(parents=True, exist_ok=True)
        (root / "runs").mkdir(exist_ok=True)

    def install_factory(self) -> None:
        shutil.copy(FAKE_FACTORY, self.root / "factory.py")

    def task(self, name: str, text: str | None = None) -> Path:
        path = self.root / "tasks" / f"{name}.md"
        path.write_text(text if text is not None else f"# {name}\n\nDo the {name} task.\n")
        return path

    def run_dir(self, run_id: str) -> Path:
        path = self.root / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def age(self, run_id: str, seconds: int) -> None:
        stamp = os.stat(self.run_dir(run_id)).st_mtime - seconds
        for path in [self.run_dir(run_id), *self.run_dir(run_id).glob("*.json")]:
            os.utime(path, (stamp, stamp))

    def worker(
        self,
        run_id: str,
        attempts: Sequence[Sequence[str]] = ((),),
        exit_code: int | None = None,
        candidate: str = CANDIDATE,
        log: bool = True,
        checks: bool = True,
    ) -> None:
        """A worker directory. `attempts` lists each attempt's failed command names, oldest first."""
        run = self.run_dir(run_id)
        final_failed = tuple(attempts[-1]) if attempts else ()
        if exit_code is None:
            exit_code = 1 if final_failed else 0
        history = []
        for number, failed in enumerate(attempts, start=1):
            checker_exit = 2 if failed else 0
            history.append(
                {"attempt": number, "candidate_revision": candidate, "checker_exit": checker_exit, "failed": list(failed)}
            )
            if failed:
                folder = run / "attempts" / str(number)
                write_check(folder, exits_failing(failed), checker_exit)
                (folder / "worker.log").write_text(f"attempt {number} output\n")
                lines = "\n".join(f"- {name}: error TS2305: Module has no exported member" for name in failed)
                (folder / "brief.md").write_text(f"# Attempt {number} failed\n\nFailed commands:\n{lines}\n\nChanged paths: src/a.ts\n")
        (run / "worker.json").write_text(
            json.dumps(
                {
                    "task": "tasks/unbound-arrows.md",
                    "base_revision": BASE,
                    "candidate_revision": candidate,
                    "exit": exit_code,
                    "model": "test-model",
                    "attempts": history,
                }
            )
        )
        if checks and attempts:
            write_check(run, exits_failing(final_failed), 2 if final_failed else 0)
        if log:
            (run / "logs").mkdir(exist_ok=True)
            (run / "logs" / "worker.log").write_text("worker output\n")

    def record(self, run_id: str, show_exit: int = 0, show_stderr: str = "") -> None:
        """`state.json` for a run directory; `state.check` comes from the run's `check.json` when present."""
        run = self.run_dir(run_id)
        (run / "request.md").write_text("request\n")
        state = {
            "run_id": run_id,
            "repo": "/app",
            "request": str(run / "request.md"),
            "request_hash": "1" * 64,
            "policy": {"base_revision": BASE, "max_changed_files": 8, "required_reviewers": 3, "required_approvals": 2},
            "policy_hash": "2" * 64,
            "base_revision": BASE,
            "candidate_revision": CANDIDATE,
            "changed_paths": ["src/a.ts", "src/b.ts"],
            "record_hash": "3" * 64,
            "status": "recorded",
        }
        if (run / "check.json").is_file():
            state["check"] = json.loads((run / "check.json").read_text())
        (run / "state.json").write_text(json.dumps(state))
        self.show(run_id, show_exit, show_stderr)

    def recorded_run(self, run_id: str, show_exit: int = 0, show_stderr: str = "") -> None:
        """A worker that passed on its first attempt, then recorded."""
        self.worker(run_id)
        self.record(run_id, show_exit, show_stderr)

    def show(self, run_id: str, exit_code: int, stderr: str = "") -> None:
        (self.run_dir(run_id) / "fake-show.txt").write_text(f"{exit_code}\n{stderr}\n")

    def update_state(self, run_id: str, **sections: object) -> None:
        path = self.run_dir(run_id) / "state.json"
        state = json.loads(path.read_text())
        state.update(sections)
        path.write_text(json.dumps(state))

    def votes(self, run_id: str, decisions: dict[str, str], recorded: bool = True) -> None:
        reviews = self.run_dir(run_id) / "reviews"
        reviews.mkdir(exist_ok=True)
        saved = {}
        for seat, decision in decisions.items():
            vote = {
                "reviewer": seat,
                "candidate_revision": CANDIDATE,
                "evidence_hash": "4" * 64,
                "decision": decision,
                "reason": f"{seat} says {decision}",
                "claims": [{"path": "src/a.ts", "note": f"{seat} note on a.ts"}],
            }
            (reviews / f"{seat}.json").write_text(json.dumps(vote))
            saved[seat] = vote
        if recorded:
            self.update_state(run_id, reviews=saved)

    def quorum(self, run_id: str, decisions: dict[str, str], required: int = 2) -> None:
        approvals = sum(1 for decision in decisions.values() if decision == "approve")
        self.update_state(
            run_id,
            quorum={"required": required, "approvals": approvals, "votes": decisions, "passed": approvals >= required},
        )

    def judge(self, run_id: str, decision: str, rework_task: bool = True, failed_seats: Sequence[str] = ()) -> None:
        brief = None
        if decision == "rework":
            brief = {
                "failed_seats": list(failed_seats),
                "excerpts": ["arrow rebinding ignores grouped elements"],
                "base_revision": BASE,
                "candidate_revision": CANDIDATE,
                "allowed_paths": ["src/a.ts"],
                "budget_remaining": 1,
            }
            (self.run_dir(run_id) / "rework-brief.md").write_text(
                "# Rework brief\n\narrow rebinding ignores grouped elements\n"
            )
            if rework_task:
                self.task(f"rework-{run_id}", "original request\n\n# Rework brief\n")
        self.update_state(
            run_id,
            judge={"decision": decision, "reason": f"judge says {decision}", "brief": brief},
            status="judged",
        )

    def decision(self, run_id: str, status: str) -> None:
        self.update_state(
            run_id,
            decision={
                "status": status,
                "reason": f"policy says {status}",
                "evidence_hash": "4" * 64,
                "review_hash": "5" * 64,
                "judge_hash": "6" * 64,
                "policy_hash": "2" * 64,
                "decision_hash": "7" * 64,
            },
            status=status,
        )

    def ready_run(self, run_id: str) -> None:
        """A run with every stage saved and the verdict `ready`."""
        everyone = dict.fromkeys(SEATS, "approve")
        self.recorded_run(run_id)
        self.votes(run_id, everyone)
        self.quorum(run_id, everyone)
        self.judge(run_id, "approve")
        self.decision(run_id, "ready")
