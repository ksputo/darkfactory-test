"""Token rules: discovery and saved files in, one visual token per stage out."""

from __future__ import annotations

import pytest

from factory_ui.model import (
    CHECK_NAMES,
    SEATS,
    Command,
    Discovery,
    KeyState,
    ShowResult,
    ShowStatus,
    StageId,
    Token,
)
from factory_ui.pipeline import Inputs, evaluate
from factory_ui.reader import list_tasks, read_run

from .labs import Lab, write_check

OK = ShowResult(ShowStatus.OK)

MODULE_COMMANDS = {
    10: set(),
    20: {Command.WORK, Command.LOOP},
    30: {Command.WORK, Command.LOOP, Command.RECORD, Command.SHOW},
    40: {Command.WORK, Command.LOOP, Command.RECORD, Command.SHOW, Command.REVIEW, Command.JUDGE},
    50: {Command.WORK, Command.LOOP, Command.RECORD, Command.SHOW, Command.REVIEW, Command.JUDGE, Command.DECIDE},
    60: set(Command),
}


@pytest.fixture
def lab(tmp_path) -> Lab:
    lab = Lab(tmp_path / "lab")
    lab.task("unbound-arrows")
    lab.task("diagram-audit")
    return lab


def pipeline(lab: Lab, module: int, run_id: str | None = None, show: ShowResult = OK, **extra):
    run = read_run(lab.root, run_id) if run_id else None
    inputs = Inputs(
        discovery=Discovery(frozenset(MODULE_COMMANDS[module])),
        tasks=tuple(list_tasks(lab.root)),
        run=run,
        show=show,
        **extra,
    )
    return evaluate(inputs)


def tokens(result) -> dict[StageId, Token]:
    return {stage.id: stage.token for stage in result.stages}


DARK_ONLY = {sid: Token.DARK for sid in StageId}


def test_the_pipeline_has_no_check_stage_and_no_check_key(lab):
    result = pipeline(lab, 60)
    assert [stage.id.value for stage in result.stages] == ["task", "worker", "panel", "quorum", "judge", "policy"]
    assert sorted(result.keys) == sorted("wvjdrRsg")


def test_module_10_lights_only_the_task(lab):
    result = pipeline(lab, 10)
    assert tokens(result) == {**DARK_ONLY, StageId.TASK: Token.IDLE}
    assert all(state.token is Token.DARK for state in result.keys.values())


def test_dark_stages_name_the_module_that_wires_them(lab):
    result = pipeline(lab, 10)
    reasons = {stage.id: stage.reason for stage in result.stages}
    assert reasons[StageId.WORKER] == "Build this in module 20"
    assert reasons[StageId.PANEL] == "Build this in module 40"
    assert reasons[StageId.QUORUM] == "Build this in module 40"
    assert reasons[StageId.JUDGE] == "Build this in module 40"
    assert reasons[StageId.POLICY] == "Build this in module 50"
    assert pipeline(lab, 10).keys["R"].reason == "Build this in module 60"


def test_discovery_failure_leaves_every_command_dark(lab):
    dark = Discovery.dark("factory.py not found")
    result = evaluate(Inputs(dark, tuple(list_tasks(lab.root)), None, OK))
    assert tokens(result) == {**DARK_ONLY, StageId.TASK: Token.IDLE}


def test_discovery_ignores_names_it_does_not_know_including_check():
    parsed = Discovery.parse("work\nloop\ncheck\nfrobnicate\n\n  show  \n")
    assert parsed.wired == {Command.WORK, Command.LOOP, Command.SHOW}


def test_module_20_worker_is_idle_and_its_key_is_lit(lab):
    result = pipeline(lab, 20)
    assert tokens(result)[StageId.WORKER] is Token.IDLE
    assert result.keys["w"].token is Token.IDLE
    assert all(token is Token.DARK for sid, token in tokens(result).items() if sid not in (StageId.TASK, StageId.WORKER))


def test_worker_that_passed_on_its_second_attempt_is_proven(lab):
    lab.worker("worker-1", attempts=[("build",), ()])
    stage = pipeline(lab, 20, "worker-1").stage(StageId.WORKER)
    assert stage.token is Token.PROVEN and stage.valid
    assert "worker-1" in stage.summary and "bbbbbbb" in stage.summary
    assert [(cell.name, cell.token) for cell in stage.attempts] == [
        ("1", Token.FAILED),
        ("2", Token.PROVEN),
        ("3", Token.DARK),
    ]
    assert [cell.name for cell in stage.cells] == list(CHECK_NAMES)
    assert all(cell.token is Token.PROVEN for cell in stage.cells)


def test_worker_that_failed_three_attempts_is_red_and_names_the_failed_checks(lab):
    lab.worker("worker-1", attempts=[("build",), ("typecheck", "build"), ("build",)])
    stage = pipeline(lab, 20, "worker-1").stage(StageId.WORKER)
    by_name = {cell.name: cell for cell in stage.cells}
    assert (stage.token, stage.reason) == (Token.FAILED, "3 of 3 attempts, failed: build")
    assert [cell.token for cell in stage.attempts] == [Token.FAILED] * 3
    assert stage.attempts[1].detail == "typecheck, build"
    assert (by_name["build"].token, by_name["build"].detail) == (Token.FAILED, "exit 2")
    assert all(by_name[name].token is Token.PROVEN for name in CHECK_NAMES if name != "build")


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"attempts": [], "exit_code": 1}, "worker exit 1"),
        ({"candidate": "a" * 40}, "no new commit"),
        ({"log": False}, "missing logs/worker.log"),
        ({"checks": False}, "missing logs/install.exit"),
    ],
)
def test_worker_failures_are_red_with_the_reason(lab, kwargs, reason):
    lab.worker("worker-1", **kwargs)
    stage = pipeline(lab, 20, "worker-1").stage(StageId.WORKER)
    assert (stage.token, stage.reason) == (Token.FAILED, reason)


def test_worker_with_a_nonzero_checker_exit_is_red_even_when_every_command_passed(lab):
    lab.worker("worker-1")
    write_check(lab.run_dir("worker-1"), dict.fromkeys(CHECK_NAMES, 0), checker_exit=3)
    stage = pipeline(lab, 20, "worker-1").stage(StageId.WORKER)
    assert (stage.token, stage.reason) == (Token.FAILED, "checker exit 3")


def test_unreadable_exit_file_is_red_with_the_decode_error(lab):
    lab.worker("worker-1")
    (lab.run_dir("worker-1") / "logs" / "code.exit").write_text("zero\n")
    stage = pipeline(lab, 20, "worker-1").stage(StageId.WORKER)
    assert (stage.token, stage.reason) == (Token.FAILED, "logs/code.exit is not an integer: 'zero'")
    assert stage.cells[2].token is Token.FAILED


def test_module_30_recorded_run_shows_the_run_id_and_leaves_the_panel_dark(lab):
    lab.recorded_run("run-1")
    result = pipeline(lab, 30, "run-1")
    assert tokens(result)[StageId.WORKER] is Token.PROVEN
    assert result.stage(StageId.WORKER).summary.startswith("run-1")
    assert tokens(result)[StageId.PANEL] is Token.DARK


def test_unrecorded_worker_blocks_the_panel_on_record(lab):
    lab.worker("worker-1")
    result = pipeline(lab, 40, "worker-1")
    assert result.stage(StageId.WORKER).token is Token.PROVEN
    panel = result.stage(StageId.PANEL)
    assert (panel.token, panel.reason) == (Token.BLOCKED, "needs record")
    assert result.keys["v"] == KeyState(Token.BLOCKED, "needs record")


def test_recorded_passing_run_unlocks_the_panel(lab):
    lab.recorded_run("run-1")
    result = pipeline(lab, 40, "run-1")
    assert result.stage(StageId.PANEL).token is Token.IDLE
    assert result.keys["v"].token is Token.IDLE
    assert result.stage(StageId.JUDGE).reason == "needs panel"


@pytest.mark.parametrize(
    ("build", "reason"),
    [
        (lambda lab: (lab.worker("run-1", attempts=[("build",)] * 3), lab.record("run-1")), "3 of 3 attempts, failed: build"),
        (lambda lab: lab.record("run-1"), "missing logs/install.exit"),
        (lambda lab: (lab.worker("run-1"), (lab.run_dir("run-1") / "check.json").unlink(), lab.record("run-1")), "missing state.check"),
    ],
)
def test_run_without_passing_check_evidence_blocks_the_panel(lab, build, reason):
    build(lab)
    result = pipeline(lab, 40, "run-1")
    worker = result.stage(StageId.WORKER)
    assert (worker.token, worker.reason) == (Token.FAILED, reason)
    panel = result.stage(StageId.PANEL)
    assert (panel.token, panel.reason) == (Token.BLOCKED, "needs passing check evidence")


def test_show_mismatch_turns_the_worker_red_and_blocks_the_panel_with_the_stderr_line(lab):
    lab.recorded_run("run-1")
    failed = ShowResult(ShowStatus.FAILED, "check evidence_hash mismatch")
    result = pipeline(lab, 40, "run-1", show=failed)
    worker = result.stage(StageId.WORKER)
    assert (worker.token, worker.reason) == (Token.FAILED, "show: check evidence_hash mismatch")
    panel = result.stage(StageId.PANEL)
    assert (panel.token, panel.reason) == (Token.BLOCKED, "show: check evidence_hash mismatch")
    assert result.keys["v"].token is Token.BLOCKED


def test_saved_stage_is_not_proven_until_show_has_answered(lab):
    lab.recorded_run("run-1")
    result = pipeline(lab, 40, "run-1", show=ShowResult(ShowStatus.UNKNOWN))
    for sid in (StageId.WORKER, StageId.PANEL):
        stage = result.stage(sid)
        assert (stage.token, stage.reason) == (Token.BLOCKED, "verifying with show")


def test_unreadable_state_json_is_a_show_failure(lab):
    lab.recorded_run("run-1")
    (lab.root / "runs" / "run-1" / "state.json").write_text("{not json")
    result = pipeline(lab, 40, "run-1")
    assert result.stage(StageId.WORKER).token is Token.FAILED
    assert "invalid JSON" in result.stage(StageId.WORKER).reason
    assert "invalid JSON" in result.stage(StageId.PANEL).reason


def test_panel_cells_show_each_seats_decision(lab):
    decisions = {"intent": "approve", "failure-modes": "rework", "operability": "approve"}
    lab.recorded_run("run-1")
    lab.votes("run-1", decisions)
    panel = pipeline(lab, 40, "run-1").stage(StageId.PANEL)
    assert panel.token is Token.PROVEN
    assert [(cell.name, cell.token, cell.detail) for cell in panel.cells] == [
        ("intent", Token.PROVEN, "approve"),
        ("failure-modes", Token.FAILED, "rework"),
        ("operability", Token.PROVEN, "approve"),
    ]
    assert [cell.name for cell in panel.cells] == list(SEATS)


def test_panel_with_two_saved_votes_is_runnable_not_proven(lab):
    lab.recorded_run("run-1")
    lab.votes("run-1", {"intent": "approve", "failure-modes": "approve"}, recorded=False)
    panel = pipeline(lab, 40, "run-1").stage(StageId.PANEL)
    assert panel.token is Token.IDLE
    assert panel.summary == "partial 2 of 3"


def test_quorum_and_judge_light_together_and_read_saved_counts(lab):
    decisions = {"intent": "approve", "failure-modes": "approve", "operability": "rework"}
    lab.recorded_run("run-1")
    lab.votes("run-1", decisions)
    lab.quorum("run-1", decisions)
    lab.judge("run-1", "approve")
    result = pipeline(lab, 40, "run-1")
    quorum, judge = result.stage(StageId.QUORUM), result.stage(StageId.JUDGE)
    assert (quorum.token, judge.token) == (Token.PROVEN, Token.PROVEN)
    assert (quorum.headline, quorum.summary.splitlines()[0]) == ("2 of 3", "passed")
    assert judge.headline == "approve"


def test_failed_quorum_is_red_and_reports_the_count(lab):
    decisions = {"intent": "approve", "failure-modes": "rework", "operability": "rework"}
    lab.recorded_run("run-1")
    lab.votes("run-1", decisions)
    lab.quorum("run-1", decisions)
    quorum = pipeline(lab, 40, "run-1").stage(StageId.QUORUM)
    assert quorum.token is Token.FAILED
    assert (quorum.headline, quorum.summary.splitlines()[0]) == ("1 of 3", "failed")


def test_judge_rework_shows_the_failed_seats_and_the_generated_task_file(lab):
    decisions = {"intent": "approve", "failure-modes": "rework", "operability": "rework"}
    lab.recorded_run("run-1")
    lab.votes("run-1", decisions)
    lab.quorum("run-1", decisions)
    lab.judge("run-1", "rework", failed_seats=["failure-modes", "operability"])
    result = pipeline(lab, 50, "run-1")
    judge = result.stage(StageId.JUDGE)
    assert judge.token is Token.FAILED
    assert judge.headline == "rework"
    assert judge.summary.splitlines() == ["brief: failure-modes, operability", "task file:", "rework-run-1.md"]
    assert result.stage(StageId.POLICY).token is Token.IDLE
    assert "rework-run-1" in [task.name for task in list_tasks(lab.root)]


def test_judge_rework_without_a_task_file_says_so(lab):
    lab.recorded_run("run-1")
    lab.votes("run-1", dict.fromkeys(SEATS, "rework"))
    lab.quorum("run-1", dict.fromkeys(SEATS, "rework"))
    lab.judge("run-1", "rework", rework_task=False, failed_seats=SEATS)
    assert pipeline(lab, 40, "run-1").stage(StageId.JUDGE).summary.splitlines()[-1] == "no task file"


def test_policy_ready_is_green(lab):
    lab.ready_run("run-1")
    result = pipeline(lab, 50, "run-1")
    policy = result.stage(StageId.POLICY)
    assert (policy.token, policy.headline) == (Token.PROVEN, "ready")
    assert all(result.stage(sid).token is Token.PROVEN for sid in StageId if sid is not StageId.TASK)


@pytest.mark.parametrize("status", ["needs-rework", "needs-human"])
def test_policy_other_verdicts_are_red_with_their_label(lab, status):
    lab.ready_run("run-1")
    lab.decision("run-1", status)
    policy = pipeline(lab, 50, "run-1").stage(StageId.POLICY)
    assert (policy.token, policy.headline) == (Token.FAILED, status)


def test_unexpected_policy_status_is_a_decode_failure_not_a_crash(lab):
    lab.ready_run("run-1")
    lab.decision("run-1", "ship-it")
    policy = pipeline(lab, 50, "run-1").stage(StageId.POLICY)
    assert policy.token is Token.FAILED
    assert "unexpected status 'ship-it'" in policy.reason


def test_module_60_lights_recovery_keys_only_for_a_recorded_run(lab):
    lab.worker("worker-1")
    assert pipeline(lab, 60, "worker-1").keys["s"].token is Token.BLOCKED
    lab.recorded_run("run-1")
    keys = pipeline(lab, 60, "run-1").keys
    assert [keys[key].token for key in "Rsg"] == [Token.IDLE] * 3


def test_record_key_needs_a_worker_for_head_that_passed(lab):
    lab.worker("worker-ok")
    lab.worker("worker-bad", attempts=[("build",)] * 3)
    assert pipeline(lab, 30).keys["r"] == KeyState(Token.BLOCKED, "needs a worker whose candidate is HEAD")
    good = pipeline(lab, 30, head_worker=read_run(lab.root, "worker-ok")).keys["r"]
    bad = pipeline(lab, 30, head_worker=read_run(lab.root, "worker-bad")).keys["r"]
    assert good == KeyState(Token.IDLE)
    assert bad == KeyState(Token.BLOCKED, "worker-bad exit 1")


def test_a_live_command_marks_its_stage_and_blocks_other_keys(lab):
    lab.recorded_run("run-1")
    result = pipeline(lab, 40, "run-1", live=Command.REVIEW)
    assert tokens(result)[StageId.PANEL] is Token.LIVE
    assert result.keys["v"].token is Token.LIVE
    assert result.keys["w"] == KeyState(Token.BLOCKED, "review is running")


def test_live_worker_keeps_its_attempt_and_check_cells(lab):
    lab.worker("worker-1", attempts=[("build",), ()])
    stage = pipeline(lab, 20, "worker-1", live=Command.WORK).stage(StageId.WORKER)
    assert stage.token is Token.LIVE
    assert len(stage.attempts) == 3 and len(stage.cells) == len(CHECK_NAMES)


def test_resume_goes_live_on_the_first_stage_without_valid_evidence(lab):
    lab.recorded_run("run-1")
    result = pipeline(lab, 60, "run-1", live=Command.RESUME)
    live = [stage.id for stage in result.stages if stage.token is Token.LIVE]
    assert live == [StageId.PANEL]
    assert result.stage(StageId.WORKER).token is Token.PROVEN


def test_a_failed_command_with_no_saved_evidence_surfaces_its_stderr_line(lab):
    lab.recorded_run("run-1")
    stage = pipeline(lab, 40, "run-1", failures={Command.REVIEW: "intent: throttled by Bedrock"}).stage(StageId.PANEL)
    assert (stage.token, stage.reason) == (Token.FAILED, "intent: throttled by Bedrock")
