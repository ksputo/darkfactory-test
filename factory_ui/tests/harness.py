"""Shared helpers for UI tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from rich.text import Text

from factory_ui.app import FactoryApp
from factory_ui.model import Config, StageId
from factory_ui.tests.labs import Lab, make_app_repo
from factory_ui.widgets import StageBox


@dataclass
class World:
    lab: Lab
    app_dir: Path
    monkeypatch: pytest.MonkeyPatch
    head: str

    def app(self, wired: str, install_factory: bool = True) -> FactoryApp:
        if install_factory:
            self.lab.install_factory()
        self.monkeypatch.setenv("FAKE_WIRED", wired)
        config = Config(self.lab.root, self.app_dir, "test-model")
        return FactoryApp(config, poll_seconds=3600.0)


def plain(widget) -> str:
    content = widget.content
    return content.plain if isinstance(content, Text) else str(content)


def box(app: FactoryApp, stage_id: StageId) -> StageBox:
    return app.query_one(f"#stage-{stage_id.value}", StageBox)


def box_text(app: FactoryApp, stage_id: StageId) -> str:
    return plain(box(app, stage_id))


def box_class(app: FactoryApp, stage_id: StageId) -> set[str]:
    return {name for name in box(app, stage_id).classes if name.startswith("-")}


MODULE_WIRED = {
    10: "",
    20: "work,loop",
    30: "work,loop,record,show",
    40: "work,loop,record,show,review,judge",
    50: "work,loop,record,show,review,judge,decide",
    60: "work,loop,record,show,review,judge,decide,recover,resume,run",
}


@pytest.fixture
def world(tmp_path, monkeypatch) -> World:
    for name in ("FAKE_FAIL", "FAKE_HOLD", "FAKE_RECORD_ID"):
        monkeypatch.delenv(name, raising=False)
    lab = Lab(tmp_path / "lab")
    lab.task("unbound-arrows")
    lab.task("diagram-audit")
    app_dir = tmp_path / "app"
    head = make_app_repo(app_dir)
    return World(lab, app_dir, monkeypatch, head)
