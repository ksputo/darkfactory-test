"""Widgets for the factory UI. They render typed state and hold no decisions."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click
from textual.screen import ModalScreen
from textual.widgets import RichLog, Static

from .model import KeySpec, KeyState, Stage, StageId, Token
from .render import box_text, entries_text, key_hint


class StageBox(Static):
    def __init__(self, stage_id: StageId, spec: KeySpec | None) -> None:
        super().__init__(id=f"stage-{stage_id.value}", classes="stage -dark")
        self.stage_id = stage_id
        self.spec = spec

    def show(self, stage: Stage, key: KeyState | None, frame: int, elapsed: float | None, focused: bool) -> None:
        self.set_classes(f"stage -{stage.token.value}" + (" -focused" if focused else ""))
        title = Text(stage.id.title, style="bold")
        self.border_title = title
        hint = key_hint(self.spec, key) if self.spec is not None and key is not None else Text("")
        self.border_subtitle = hint
        self.tooltip = stage.reason if stage.token is Token.DARK else None
        self.update(box_text(stage, frame, elapsed, max(self.size.width, 10)))

    def on_click(self, event: Click) -> None:
        self.app.focus_stage(self.stage_id)  # type: ignore[attr-defined]


class Arrow(Static):
    def __init__(self) -> None:
        super().__init__("→", classes="arrow")


class ListPanel(Static):
    def __init__(self, title: str, panel_id: str, empty: str) -> None:
        super().__init__(id=panel_id, classes="list")
        self.border_title = title
        self.empty = empty

    def show(self, entries: list[tuple[Token, str, str]], selected: int) -> None:
        height = max(1, self.content_size.height or 5)
        self.update(entries_text(entries, selected, height, self.empty))


class LogScreen(ModalScreen[None]):
    BINDINGS = [Binding("l,escape,q", "close", "close")]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self.title_text = title
        self.body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="log-dialog"):
            yield Static(Text(self.title_text, style="bold"), id="log-title")
            yield RichLog(id="full-log", wrap=False, markup=False, highlight=False, max_lines=5000)
            yield Static(Text("l / esc / q close", style="dim"), id="log-hint")

    def on_mount(self) -> None:
        view = self.query_one("#full-log", RichLog)
        for line in self.body.splitlines() or ["(empty)"]:
            view.write(Text(line))

    def action_close(self) -> None:
        self.dismiss(None)
