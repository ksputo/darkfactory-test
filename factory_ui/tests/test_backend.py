"""The backend is the only subprocess boundary. These tests run the fake factory through `uv run`."""

from __future__ import annotations

import pytest

from factory_ui.backend import Backend
from factory_ui.model import Command, ShowStatus

from .labs import Lab, make_app_repo


@pytest.fixture
def lab(tmp_path) -> Lab:
    lab = Lab(tmp_path / "lab")
    lab.install_factory()
    return lab


def backend(lab: Lab, app=None) -> Backend:
    return Backend(lab.root, app or lab.root / "no-app")


async def test_discovery_reads_the_wired_command_list(lab, monkeypatch):
    monkeypatch.setenv("FAKE_WIRED", "work,loop,record,show")
    found = await backend(lab).discover()
    assert found.wired == {Command.WORK, Command.LOOP, Command.RECORD, Command.SHOW}
    assert found.problem == ""


async def test_missing_factory_py_is_dark_without_starting_a_process(tmp_path):
    lab = Lab(tmp_path / "lab")
    subject = backend(lab)
    found = await subject.discover()
    assert found.wired == frozenset()
    assert "factory.py not found" in found.problem
    assert subject.started == []


async def test_discovery_exit_nonzero_keeps_the_underlying_error(lab):
    (lab.root / "factory.py").write_text("import sys\nprint('boom: no strands installed', file=sys.stderr)\nsys.exit(3)\n")
    found = await backend(lab).discover()
    assert found.wired == frozenset()
    assert found.problem == "factory.py exit 3: boom: no strands installed"


async def test_show_exit_zero_is_ok(lab, monkeypatch):
    monkeypatch.setenv("FAKE_WIRED", "show")
    lab.record("run-1")
    assert (await backend(lab).show("run-1")).status is ShowStatus.OK


async def test_show_nonzero_carries_the_first_stderr_line(lab, monkeypatch):
    monkeypatch.setenv("FAKE_WIRED", "show")
    lab.record("run-1", show_exit=1, show_stderr="review_hash mismatch\nsecond line")
    result = await backend(lab).show("run-1")
    assert (result.status, result.reason) == (ShowStatus.FAILED, "review_hash mismatch")


async def test_run_command_streams_lines_and_returns_exit_and_stdout(lab, monkeypatch):
    monkeypatch.setenv("FAKE_WIRED", "record")
    monkeypatch.setenv("FAKE_RECORD_ID", "run-9")
    seen: list[str] = []
    subject = backend(lab)
    result = await subject.run_command(Command.RECORD, ["tasks/x.md"], seen.append)
    assert result.ok
    assert result.completed.stdout == ("run-9",)
    assert "fake record starting" in seen and "run-9" in seen
    assert subject.started == [(Command.RECORD, "tasks/x.md")]


async def test_failed_command_reason_is_the_first_stderr_line(lab, monkeypatch):
    monkeypatch.setenv("FAKE_WIRED", "review")
    monkeypatch.setenv("FAKE_FAIL", "review")
    result = await backend(lab).run_command(Command.REVIEW, ["run-1"], lambda line: None)
    assert not result.ok
    assert result.reason == "fake: review failed on purpose"


async def test_unrunnable_runner_reports_the_os_error(lab):
    subject = Backend(lab.root, lab.root, runner=("no-such-runner-binary",))
    found = await subject.discover()
    assert "cannot start no-such-runner-binary" in found.problem


async def test_app_status_reads_head_and_cleanliness(tmp_path, lab):
    app = tmp_path / "app"
    head = make_app_repo(app)
    clean = await backend(lab, app).app_status()
    assert (clean.revision, clean.head, clean.dirty, clean.problem) == (head, head[: len(clean.head)], False, "")
    assert len(clean.head) >= 7
    (app / "README.md").write_text("changed\n")
    assert (await backend(lab, app).app_status()).dirty is True


async def test_app_status_for_a_missing_checkout_says_not_found(lab):
    status = await backend(lab).app_status()
    assert (status.head, status.dirty, status.problem) == ("", None, "not found")
