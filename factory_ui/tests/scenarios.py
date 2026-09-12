"""The six representative lab states used by UI tests and screenshots."""

from __future__ import annotations

from collections.abc import Callable

from factory_ui.model import SEATS
from factory_ui.tests.labs import Lab


def module_10(lab: Lab) -> None:
    """Starter: tasks only, no factory.py."""


def worker_proven(lab: Lab) -> None:
    """Module 20: the first attempt failed `build`, the second passed every check."""
    lab.worker("worker-20261016-094000", attempts=[("build",)] * 3)
    lab.age("worker-20261016-094000", 600)
    lab.worker("worker-20261016-101500", attempts=[("build",), ()])


def worker_failed(lab: Lab) -> None:
    """Three attempts, each failing `build`: the worker stops and a human reads the brief."""
    lab.worker("worker-20261016-111500", attempts=[("build",), ("typecheck", "build"), ("build",)])


def judge_rework(lab: Lab) -> None:
    decisions = {"intent": "approve", "failure-modes": "rework", "operability": "rework"}
    lab.recorded_run("run-ui-1")
    lab.votes("run-ui-1", decisions)
    lab.quorum("run-ui-1", decisions)
    lab.judge("run-ui-1", "rework", failed_seats=["failure-modes", "operability"])


def ready(lab: Lab) -> None:
    lab.ready_run("run-ui-1")
    lab.worker("worker-20261016-090000", attempts=[("build",)] * 3)
    lab.age("worker-20261016-090000", 900)
    lab.recorded_run("run-ui-0", show_exit=1, show_stderr="judge_hash does not match state.json")
    lab.age("run-ui-0", 600)


def stopped_save(lab: Lab) -> None:
    """Module 60: recorded with passing check evidence, then the process stopped after saving the votes."""
    lab.recorded_run("run-ui-1")
    lab.votes("run-ui-1", dict.fromkeys(SEATS, "approve"), recorded=False)


SCENARIOS: dict[str, tuple[int, Callable[[Lab], None]]] = {
    "module10-dark": (10, module_10),
    "module20-worker-proven": (20, worker_proven),
    "module40-worker-failed": (40, worker_failed),
    "module40-judge-rework": (40, judge_rework),
    "module50-ready": (50, ready),
    "module60-live-resume": (60, stopped_save),
}
