"""Drive the real app with `App.run_test` against the fake factory. Assertions read model state and widget text."""

from __future__ import annotations

import asyncio
import time

import pytest
from rich.cells import cell_len
from rich.console import Console
from rich.text import Text

from factory_ui.app import FactoryApp
from factory_ui.model import KEYS, Command, StageId, Token
from factory_ui.tests import scenarios
from factory_ui.tests.harness import MODULE_WIRED, box, box_class, box_text, plain
from factory_ui.widgets import LogScreen

SIZES = [(120, 40), (160, 50)]


async def settle(app: FactoryApp, pilot) -> None:
    await pilot.pause()
    await app.refresh_now()
    await pilot.pause()


async def until(condition, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached before the deadline"
        await asyncio.sleep(0.02)


def tokens(app: FactoryApp) -> dict[StageId, Token]:
    return {stage.id: stage.token for stage in app.pipeline.stages}


async def test_starter_without_factory_py_is_dark_except_task_and_app_status(world):
    app = world.app("", install_factory=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        header = plain(app.query_one("#header"))
        assert str(world.app_dir) in header and "clean" in header and "test-model" in header
        assert f"@ {world.head[:7]}" in header
        assert "factory.py" in header and "not found" in header
        assert box_class(app, StageId.TASK) >= {"-idle"}
        for sid in StageId:
            if sid is not StageId.TASK:
                assert box_class(app, sid) == {"-dark"}, sid
        assert "Build this in module 20" in box_text(app, StageId.WORKER)
        await pilot.press("q")
        await pilot.pause()
        assert not app.is_running or app._exit


async def test_dirty_application_checkout_is_shown_in_the_header(world):
    (world.app_dir / "README.md").write_text("edited\n")
    app = world.app("", install_factory=False)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        assert "dirty" in plain(app.query_one("#header"))


@pytest.mark.parametrize("module", [10, 20, 30, 40, 50, 60])
async def test_each_module_lights_exactly_its_stages_for_a_fresh_recorded_run(world, module):
    world.lab.recorded_run("run-1")
    app = world.app(MODULE_WIRED[module])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        lit = {sid for sid in StageId if "-dark" not in box_class(app, sid)}
        wired = {
            10: {StageId.TASK},
            20: {StageId.TASK, StageId.WORKER},
            30: {StageId.TASK, StageId.WORKER},
            40: set(StageId) - {StageId.POLICY},
            50: set(StageId),
            60: set(StageId),
        }[module]
        assert lit == wired
        assert tokens(app)[StageId.TASK] is Token.IDLE
        if module >= 30:
            assert tokens(app)[StageId.WORKER] is Token.PROVEN
        if module >= 40:
            assert tokens(app)[StageId.PANEL] is Token.IDLE
            assert tokens(app)[StageId.JUDGE] is Token.BLOCKED
            assert "🔒" in box_text(app, StageId.JUDGE) and "needs panel" in box_text(app, StageId.JUDGE)
        if module >= 50:
            assert tokens(app)[StageId.POLICY] is Token.BLOCKED
        first_line = plain(app.query_one("#keys")).split("\n")[0]
        for spec in KEYS:
            lit = app.pipeline.keys[spec.key].token is not Token.DARK
            assert (f"{spec.key} {spec.label}" in first_line) is lit, (spec, first_line)
        assert "c check" not in first_line


async def test_footer_lists_the_spec_keys_and_no_check_key(world):
    world.lab.recorded_run("run-1")
    app = world.app(MODULE_WIRED[60])
    async with app.run_test(size=(160, 50)) as pilot:
        await settle(app, pilot)
        footer = plain(app.query_one("#keys"))
        for label in ("w work", "v review", "j judge", "d decide", "r record", "R recover", "s resume", "g run"):
            assert label in footer, label
        for label in ("[ ] run", "←→ stage", "↑↓ task", "⏎ preview", "l log", "q quit"):
            assert label in footer, label
        assert "check" not in footer
        await pilot.press("c")
        assert app.backend.started == []


async def test_show_stderr_line_turns_the_worker_red_and_blocks_the_panel(world):
    world.lab.recorded_run("run-1", show_exit=1, show_stderr="record_hash does not match state.json")
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        assert box_class(app, StageId.WORKER) == {"-failed"}
        assert "record_hash does not match" in box_text(app, StageId.WORKER).replace("\n", "")
        assert box_class(app, StageId.PANEL) == {"-blocked"}
        await pilot.press("v")
        assert "record_hash does not match state.json" in app.status_text.plain
        assert app.backend.started == []


async def test_dark_key_explains_the_module_and_launches_nothing(world):
    app = world.app(MODULE_WIRED[10])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("w")
        assert "Build this in module 20" in app.status_text.plain
        assert app.backend.started == []


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        (lambda lab: lab.worker("worker-1"), "needs record"),
        (lambda lab: (lab.worker("run-1", attempts=[("build",)] * 3), lab.record("run-1")), "needs passing check evidence"),
    ],
)
async def test_blocked_review_key_names_what_is_missing(world, build, reason):
    build(world.lab)
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        assert reason in box_text(app, StageId.PANEL)
        await pilot.press("v")
        assert f"review is blocked: {reason}" in app.status_text.plain
        assert app.backend.started == []


async def test_keys_launch_the_mapped_commands_with_the_selected_task_and_run(world):
    world.lab.recorded_run("run-1")
    app = world.app(MODULE_WIRED[60])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("down")
        await pilot.press("w")
        await app.wait_idle()
        await pilot.press("v")
        await app.wait_idle()
        for key in "Rsg":
            await pilot.press(key)
            await app.wait_idle()
        assert app.backend.started == [
            (Command.WORK, "tasks/unbound-arrows.md"),
            (Command.REVIEW, "run-1"),
            (Command.RECOVER, "run-1"),
            (Command.RESUME, "run-1"),
            (Command.RUN, "tasks/unbound-arrows.md"),
        ]


async def test_second_key_press_while_live_does_not_launch(world, tmp_path, monkeypatch):
    world.lab.recorded_run("run-1")
    gate = tmp_path / "release"
    monkeypatch.setenv("FAKE_HOLD", str(gate))
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("v")
        assert app.live_command is not None
        assert box_class(app, StageId.PANEL) == {"-live"}
        await pilot.press("w")
        await pilot.press("v")
        assert "review run-1 is still running" in app.status_text.plain
        assert app.backend.started == [(Command.REVIEW, "run-1")]
        gate.write_text("go")
        await app.wait_idle()
        assert app.live_command is None
        assert app.backend.started == [(Command.REVIEW, "run-1")]
        assert "finished, exit 0" in app.status_text.plain


async def test_live_stage_shows_elapsed_time_and_the_tail_of_command_output(world, tmp_path, monkeypatch):
    world.lab.recorded_run("run-1")
    gate = tmp_path / "release"
    monkeypatch.setenv("FAKE_HOLD", str(gate))
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("v")
        await until(lambda: "fake review starting" in list(app.live_command.lines))
        app._render()
        assert "live" in box_text(app, StageId.PANEL) and "s\n" in box_text(app, StageId.PANEL) + "\n"
        tail = plain(app.query_one("#log-tail"))
        assert "review run-1" in tail and "fake review starting" in tail
        gate.write_text("go")
        await app.wait_idle()


async def test_live_work_tails_the_new_worker_log(world, tmp_path, monkeypatch):
    gate = tmp_path / "release"
    monkeypatch.setenv("FAKE_HOLD", str(gate))
    app = world.app(MODULE_WIRED[20])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("w")
        world.lab.worker("worker-live", attempts=[])
        (world.lab.run_dir("worker-live") / "logs" / "worker.log").write_text("agent: editing src/a.ts\n")
        app._render()
        assert box_class(app, StageId.WORKER) == {"-live"}
        assert "agent: editing src/a.ts" in plain(app.query_one("#log-tail"))
        gate.write_text("go")
        await app.wait_idle()


async def test_failed_command_keeps_the_stderr_line_and_marks_the_stage(world, monkeypatch):
    world.lab.recorded_run("run-1")
    monkeypatch.setenv("FAKE_FAIL", "review")
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("v")
        await app.wait_idle()
        assert "exit 1: fake: review failed on purpose" in app.status_text.plain
        assert box_class(app, StageId.PANEL) == {"-failed"}
        assert "fake: review failed on purpose" in box_text(app, StageId.PANEL).replace("\n", " ")
        assert "exit 1" in plain(app.query_one("#log-tail"))


async def test_record_passes_the_latest_worker_for_head_and_selects_the_printed_run(world, monkeypatch):
    monkeypatch.setenv("FAKE_RECORD_ID", "run-new")
    world.lab.worker("worker-old", candidate=world.head)
    world.lab.age("worker-old", 600)
    world.lab.worker("worker-head", candidate=world.head)
    world.lab.age("worker-head", 300)
    world.lab.worker("worker-other")
    app = world.app(MODULE_WIRED[30])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        assert app.selected_run == "worker-other"
        await pilot.press("r")
        await app.wait_idle()
        assert app.backend.started == [(Command.RECORD, "tasks/unbound-arrows.md", "runs/worker-head")]
        assert app.selected_run == "run-new"


async def test_record_is_blocked_without_a_worker_for_head(world):
    world.lab.worker("worker-other")
    app = world.app(MODULE_WIRED[30])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("r")
        assert "record is blocked: needs a worker whose candidate is HEAD" in app.status_text.plain
        assert app.backend.started == []


async def test_brackets_cycle_runs_newest_first_and_wrap(world):
    for index, run_id in enumerate(["run-a", "run-b", "run-c"]):
        world.lab.recorded_run(run_id, show_exit=1 if run_id == "run-b" else 0, show_stderr="bad" if run_id == "run-b" else "")
        world.lab.age(run_id, (3 - index) * 100)
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        assert [ref.run_id for ref in app.run_refs] == ["run-c", "run-b", "run-a"]
        assert app.selected_run == "run-c"
        listing = plain(app.query_one("#runs"))
        assert "✔ run-c" in listing and "✘ run-b" in listing and "✔ run-a" in listing
        await pilot.press("right_square_bracket")
        assert app.selected_run == "run-b"
        await settle(app, pilot)
        assert box_class(app, StageId.WORKER) == {"-failed"}
        await pilot.press("right_square_bracket", "right_square_bracket")
        assert app.selected_run == "run-c"
        await pilot.press("left_square_bracket")
        assert app.selected_run == "run-a"


async def test_worker_proven_after_a_retry_shows_attempts_and_checks(world):
    scenarios.worker_proven(world.lab)
    app = world.app(MODULE_WIRED[20])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        assert app.selected_run == "worker-20261016-101500"
        text = box_text(app, StageId.WORKER)
        assert box_class(app, StageId.WORKER) == {"-proven"}
        assert "try ✘1 ✔2 ○3" in text
        assert all(f"✔ {name}" in text for name in ("install", "typecheck", "build", "diagram-audit"))
        listing = plain(app.query_one("#runs"))
        assert "✔ worker-20261016-101500" in listing and "✘ worker-20261016-094000" in listing
        await pilot.press("right")
        evidence = plain(app.query_one("#evidence"))
        assert "✘ 1  bbbbbbb  checker_exit 2  failed: build" in evidence
        assert "✔ 2  bbbbbbb  checker_exit 0  passed" in evidence
        assert "✔ build          exit 0   39 B" in evidence
        assert "check.json.checker_exit: 0" in evidence
        assert "last brief: attempts/1/brief.md" in evidence


async def test_worker_failed_after_three_attempts_is_red_and_l_opens_the_last_brief(world):
    scenarios.worker_failed(world.lab)
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        text = box_text(app, StageId.WORKER)
        assert box_class(app, StageId.WORKER) == {"-failed"}
        assert "3 of 3 attempts, failed: build" in text.replace("\n", " ").replace("  ", " ")
        assert "try ✘1 ✘2 ✘3" in text
        assert "✘ build" in text and "✔ install" in text and "✔ diagram-audit" in text
        assert "needs record" in box_text(app, StageId.PANEL)
        await pilot.press("right")
        evidence = plain(app.query_one("#evidence"))
        assert "✘ 2  bbbbbbb  checker_exit 2  failed: typecheck, build" in evidence
        assert "✘ build          exit 2   39 B" in evidence and "✔ install        exit 0   45 B" in evidence
        assert "last brief: attempts/3/brief.md" in evidence
        await pilot.press("l")
        await pilot.pause()
        assert isinstance(app.screen, LogScreen)
        assert "== attempts/3/brief.md ==" in app.screen.body and "# Attempt 3 failed" in app.screen.body
        assert "worker output" not in app.screen.body


async def test_judge_rework_shows_failed_seats_task_file_and_quorum(world):
    scenarios.judge_rework(world.lab)
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        judge = box_text(app, StageId.JUDGE).replace("\n", "")
        assert "rework" in judge and "brief: failure-modes, operability" in judge and "rework-run-ui-1.md" in judge
        assert "1 of 3" in box_text(app, StageId.QUORUM) and "failed" in box_text(app, StageId.QUORUM)
        panel = box_text(app, StageId.PANEL)
        assert "✔ intent" in panel and "✘ failure-modes" in panel and "src/a.ts" in panel
        await pilot.press("right", "right", "right", "right")
        assert app.stage_focus is StageId.JUDGE
        evidence = plain(app.query_one("#evidence"))
        assert "failed_seats: failure-modes, operability" in evidence
        assert "arrow rebinding ignores grouped elements" in evidence and "tasks/rework-run-ui-1.md" in evidence
        assert "budget_remaining: 1" in evidence
        names = [task.name for task in app.tasks]
        assert "rework-run-ui-1" in names
        assert "rework" in plain(app.query_one("#task-list"))


async def test_policy_ready_is_green_and_every_stage_is_proven(world):
    scenarios.ready(world.lab)
    app = world.app(MODULE_WIRED[50])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        assert app.selected_run == "run-ui-1"
        assert box_class(app, StageId.POLICY) == {"-proven"}
        assert "ready" in box_text(app, StageId.POLICY)
        for sid in StageId:
            if sid is not StageId.TASK:
                assert "-proven" in box_class(app, sid), sid
        app.focus_stage(StageId.POLICY)
        assert "policy.max_changed_files: 8" in plain(app.query_one("#evidence"))
        assert "decision_hash: " + "7" * 64 in plain(app.query_one("#evidence"))


async def test_enter_previews_the_selected_task(world):
    world.lab.task("diagram-audit", "# Diagram Audit\n\nAudit every arrow.\n")
    app = world.app(MODULE_WIRED[20])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("right", "right")
        assert "Audit every arrow" not in plain(app.query_one("#evidence"))
        await pilot.press("enter")
        assert app.stage_focus is StageId.TASK
        assert "Audit every arrow." in plain(app.query_one("#evidence"))
        await pilot.press("down")
        assert "Do the unbound-arrows task." in plain(app.query_one("#evidence"))


async def test_full_log_view_opens_the_worker_log_for_a_proven_worker(world):
    scenarios.worker_proven(world.lab)
    app = world.app(MODULE_WIRED[20])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("right")
        await pilot.press("l")
        await pilot.pause()
        assert isinstance(app.screen, LogScreen)
        assert "== logs/worker.log ==" in app.screen.body and "worker output" in app.screen.body
        assert "brief.md" not in app.screen.body
        await pilot.press("w")
        assert app.backend.started == []
        await pilot.press("l")
        await pilot.pause()
        assert not isinstance(app.screen, LogScreen)


async def test_quit_while_live_needs_a_second_press(world, tmp_path, monkeypatch):
    world.lab.recorded_run("run-1")
    monkeypatch.setenv("FAKE_HOLD", str(tmp_path / "never"))
    app = world.app(MODULE_WIRED[40])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("v")
        await pilot.press("q")
        assert app.is_running and "Press q again" in app.status_text.plain
        await pilot.press("q")
        await pilot.pause()
        await until(lambda: app.live_command is None)


async def test_session_writes_nothing_under_runs_or_tasks(world):
    scenarios.judge_rework(world.lab)
    scenarios.worker_failed(world.lab)

    def snapshot():
        found = {}
        for top in ("runs", "tasks"):
            for path in (world.lab.root / top).rglob("*"):
                stat = path.stat()
                found[str(path)] = (stat.st_mtime_ns, stat.st_size)
        return found

    before = snapshot()
    app = world.app(MODULE_WIRED[50])
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await pilot.press("right", "right", "down", "enter", "left_square_bracket", "right", "l")
        await pilot.pause()
        await pilot.press("escape")
        await app.refresh_now()
    assert snapshot() == before
    assert not (world.app_dir / "runs").exists()


@pytest.mark.parametrize("size", SIZES)
async def test_no_label_is_cut_off_at_either_terminal_size(world, size):
    scenarios.judge_rework(world.lab)
    scenarios.worker_failed(world.lab)
    world.lab.recorded_run("run-ui-2")
    world.lab.age("run-ui-2", 1)
    world.lab.ready_run("run-ui-3")
    world.lab.decision("run-ui-3", "needs-rework")
    world.lab.age("run-ui-3", 2)
    app = world.app(MODULE_WIRED[60])
    async with app.run_test(size=size) as pilot:
        await settle(app, pilot)
        for run_id in ("run-ui-2", "run-ui-1", "run-ui-3", "worker-20261016-111500"):
            app.selected_run = run_id
            app._render()
            await pilot.pause()
            for sid in StageId:
                widget = box(app, sid)
                width = widget.content_size.width
                title = widget.border_title
                assert cell_len(Text.from_markup(str(title)).plain) <= widget.outer_size.width - 4, (sid, title)
                lines = box_text(app, sid).splitlines()
                wrapped = box(app, sid).content.wrap(Console(), width)
                assert len(wrapped) <= widget.content_size.height, (sid, run_id, [line.plain for line in wrapped])
                for index, line in enumerate(lines):
                    is_label = index == 0 or line.startswith(("✔", "✘", "○", "◇", "🔒", "try"))
                    if is_label or sid in (StageId.QUORUM, StageId.POLICY, StageId.TASK):
                        assert cell_len(line) <= width, (sid, line, width)
        assert app.size == size
        assert box(app, StageId.POLICY).content_size.width >= len("needs-rework")
        assert box(app, StageId.WORKER).content_size.width >= len("✔ diagram-audit")
        assert box(app, StageId.PANEL).content_size.width >= len("✔ failure-modes")
