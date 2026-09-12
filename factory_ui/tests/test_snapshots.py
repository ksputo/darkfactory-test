"""Render the six representative module states to SVG.

Set FACTORY_UI_SNAPSHOT_DIR to keep the files; otherwise they go to pytest's temp directory.
Each test asserts on text in the rendered SVG so a blank screenshot cannot pass.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from factory_ui.model import StageId
from factory_ui.tests import scenarios
from factory_ui.tests.harness import MODULE_WIRED
from factory_ui.tests.test_app import settle, until

SIZE = tuple(int(part) for part in os.environ.get("FACTORY_UI_SNAPSHOT_SIZE", "120x40").split("x"))

FOCUS = {
    "module10-dark": StageId.TASK,
    "module20-worker-proven": StageId.WORKER,
    "module40-worker-failed": StageId.WORKER,
    "module40-judge-rework": StageId.JUDGE,
    "module50-ready": StageId.POLICY,
    "module60-live-resume": StageId.PANEL,
}

EXPECTED_TEXT = {
    "module10-dark": ["module 50", "module 40", "Build this in module"],
    "module20-worker-proven": ["worker-20261016-101500", "bbbbbbb", "checker_exit 2  failed: build"],
    "module40-worker-failed": ["3 of 3", "diagram-audit", "attempts/3/brief.md"],
    "module40-judge-rework": ["task file:", "brief:", "failed_seats"],
    "module50-ready": ["ready", "judge_hash"],
    "module60-live-resume": ["live", "fake resume starting"],
}


@pytest.mark.parametrize("name", list(scenarios.SCENARIOS))
async def test_module_state_renders_to_svg(world, tmp_path, monkeypatch, name):
    module, build = scenarios.SCENARIOS[name]
    build(world.lab)
    gate = tmp_path / "release"
    if name == "module60-live-resume":
        monkeypatch.setenv("FAKE_HOLD", str(gate))
    app = world.app(MODULE_WIRED[module], install_factory=module > 10)
    out_dir = Path(os.environ.get("FACTORY_UI_SNAPSHOT_DIR", tmp_path))
    out_dir.mkdir(parents=True, exist_ok=True)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        if name == "module60-live-resume":
            await pilot.press("s")
            await until(lambda: "fake resume starting" in list(app.live_command.lines))
            app._render()
        app.focus_stage(FOCUS[name])
        await pilot.pause()
        svg = Path(app.save_screenshot(filename=f"{name}.svg", path=str(out_dir)))
        gate.write_text("go")
        await app.wait_idle() if app.live_command else None
    content = svg.read_text()
    assert svg.stat().st_size > 5000
    for text in EXPECTED_TEXT[name]:
        assert text.replace(" ", "&#160;") in content or text in content, text
