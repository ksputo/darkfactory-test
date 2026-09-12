"""The factory UI: a view and controller over `factory.py` and the files it saves."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Static

from .backend import Backend, CommandResult
from .model import (
    KEYS,
    PIPELINE,
    Command,
    Config,
    Discovery,
    KeySpec,
    Pipeline,
    RunKind,
    RunRef,
    RunView,
    ShowResult,
    ShowStatus,
    StageId,
    TaskRef,
    Token,
)
from .pipeline import Inputs, evaluate, run_token
from .reader import list_runs, list_tasks, read_run, run_signature
from .render import (
    SPINNER,
    TOKEN_STYLE,
    evidence_text,
    glyph,
    header_text,
    keybar_text,
    run_label,
)
from .widgets import Arrow, ListPanel, LogScreen, StageBox

TAIL_LINES = 5
POLL_SECONDS = 1.0
RUN_STARTERS = (Command.WORK, Command.LOOP, Command.RECORD, Command.RUN)
SPEC_BY_KEY = {spec.key: spec for spec in KEYS}


@dataclass
class LiveCommand:
    command: Command
    args: tuple[str, ...]
    run_id: str | None
    started: float
    started_ns: int
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=2000))

    def label(self) -> str:
        return " ".join([self.command.value, *self.args])


@dataclass(frozen=True)
class Finished:
    label: str
    exit_code: int
    reason: str
    lines: tuple[str, ...]


def tail_of(path: Path, count: int) -> list[str]:
    try:
        data = path.read_bytes()[-8192:]
    except OSError:
        return []
    return data.decode(errors="replace").splitlines()[-count:]


class FactoryApp(App[None]):
    CSS_PATH = "factory_ui.tcss"
    TITLE = "Factory"
    BINDINGS = [
        *[Binding(spec.key, f"launch('{spec.key}')", spec.label, show=False) for spec in KEYS],
        Binding("left_square_bracket", "cycle_run(-1)", "previous run", show=False),
        Binding("right_square_bracket", "cycle_run(1)", "next run", show=False),
        Binding("left", "move_stage(-1)", "previous stage", show=False),
        Binding("right", "move_stage(1)", "next stage", show=False),
        Binding("up", "move_task(-1)", "previous task", show=False),
        Binding("down", "move_task(1)", "next task", show=False),
        Binding("enter", "preview_task", "preview task", show=False),
        Binding("l", "toggle_log", "log", show=False),
        Binding("pageup", "scroll_evidence(-1)", show=False),
        Binding("pagedown", "scroll_evidence(1)", show=False),
        Binding("q", "quit_app", "quit", show=False),
    ]

    def __init__(self, config: Config, runner: tuple[str, ...] = ("uv", "run"), poll_seconds: float = POLL_SECONDS):
        super().__init__()
        self.config = config
        self.backend = Backend(config.lab, config.app, runner)
        self.poll_seconds = poll_seconds
        self.discovery = Discovery.dark("discovering")
        self._factory_stamp: int | None = -1
        self.app_status = None
        self.run_refs: list[RunRef] = []
        self.tasks: list[TaskRef] = []
        self.views: dict[str, tuple[tuple, RunView]] = {}
        self.shows: dict[str, tuple[tuple, ShowResult]] = {}
        self.selected_run: str | None = None
        self.task_index = 0
        self.stage_focus = StageId.TASK
        self.live_command: LiveCommand | None = None
        self.finished: Finished | None = None
        self.failures: dict[tuple[str | None, Command], str] = {}
        self.pipeline: Pipeline | None = None
        self.status_text = Text("")
        self._frame = 0
        self._refresh_lock = asyncio.Lock()
        self._command_task: asyncio.Task[None] | None = None
        self._quit_armed = False
        self._view_ready = False

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with Horizontal(id="pipeline"):
            for index, stage_id in enumerate(PIPELINE):
                spec = next((spec for spec in KEYS if spec.stage is stage_id), None)
                if index:
                    yield Arrow()
                yield StageBox(stage_id, spec)
        with Horizontal(id="middle"):
            with Vertical(id="side"):
                yield ListPanel("Runs  [ ]", "runs", "No runs yet")
                yield ListPanel("Tasks  ↑↓", "task-list", "No tasks/*.md")
            with VerticalScroll(id="evidence-scroll", can_focus=False):
                yield Static(id="evidence")
        yield Static(id="log-tail")
        yield Static(id="status")
        yield Static(id="keys")

    async def on_mount(self) -> None:
        self.query_one("#log-tail").border_title = "Log"
        self._view_ready = True
        self._render()
        self.set_interval(self.poll_seconds, self._poll)
        self.set_interval(0.2, self._tick)
        self.run_worker(self.refresh_now(), exclusive=False)

    def on_unmount(self) -> None:
        self.backend.terminate()

    # ----- state gathering -------------------------------------------------

    def _poll(self) -> None:
        if not self._refresh_lock.locked():
            self.run_worker(self.refresh_now(), exclusive=False)

    async def refresh_now(self) -> None:
        async with self._refresh_lock:
            await self._discover_if_changed()
            self.app_status = await self.backend.app_status()
            self._scan()
            self._render()
            await self._validate_runs()
            self._render()

    async def _discover_if_changed(self, force: bool = False) -> None:
        stamp = self._factory_stamp_now()
        if force or stamp != self._factory_stamp:
            self._factory_stamp = stamp
            self.discovery = await self.backend.discover()

    def _factory_stamp_now(self) -> int | None:
        try:
            return self.backend.factory_file.stat().st_mtime_ns
        except OSError:
            return None

    def _scan(self) -> None:
        lab = self.config.lab
        self.run_refs = list_runs(lab)
        self.tasks = list_tasks(lab)
        self.task_index = min(self.task_index, max(0, len(self.tasks) - 1))
        known = {ref.run_id for ref in self.run_refs}
        for run_id in known:
            signature = run_signature(lab, run_id)
            if run_id not in self.views or self.views[run_id][0] != signature:
                try:
                    self.views[run_id] = (signature, read_run(lab, run_id))
                except OSError:
                    continue
        for stale in set(self.views) - known:
            del self.views[stale]
            self.shows.pop(stale, None)
        if self.selected_run not in known:
            self.selected_run = self.run_refs[0].run_id if self.run_refs else None

    async def _validate_runs(self) -> None:
        if not self.discovery.is_wired(Command.SHOW):
            return
        order = sorted(self.views, key=lambda run_id: run_id != self.selected_run)
        for run_id in order:
            signature, view = self.views[run_id]
            cached = self.shows.get(run_id)
            if view.kind is not RunKind.RECORD or (cached and cached[0] == signature):
                continue
            self.shows[run_id] = (signature, await self.backend.show(run_id))
            if run_id == self.selected_run:
                self._render()

    def _show_for(self, run_id: str) -> ShowResult:
        if not self.discovery.is_wired(Command.SHOW):
            return ShowResult(ShowStatus.UNWIRED)
        signature, _ = self.views[run_id]
        cached = self.shows.get(run_id)
        if cached and cached[0] == signature:
            return cached[1]
        return ShowResult(ShowStatus.UNKNOWN)

    def selected_view(self) -> RunView | None:
        return self.views[self.selected_run][1] if self.selected_run in self.views else None

    def selected_task(self) -> TaskRef | None:
        return self.tasks[self.task_index] if self.tasks else None

    def head_worker(self) -> RunView | None:
        """The latest `runs/worker-*` directory whose candidate is the application HEAD."""
        revision = self.app_status.revision if self.app_status is not None else ""
        if not revision:
            return None
        for ref in self.run_refs:
            view = self.views[ref.run_id][1] if ref.run_id in self.views else None
            if (
                view is not None
                and view.kind is RunKind.WORKER
                and view.run_id.startswith("worker-")
                and view.worker is not None
                and view.worker.candidate_revision == revision
            ):
                return view
        return None

    def _inputs(self) -> Inputs:
        run = self.selected_view()
        show = self._show_for(run.run_id) if run else ShowResult(ShowStatus.UNWIRED)
        failures = {
            command: reason
            for (run_id, command), reason in self.failures.items()
            if run_id is None or run_id == self.selected_run
        }
        return Inputs(
            discovery=self.discovery,
            tasks=tuple(self.tasks),
            run=run,
            show=show,
            live=self.live_command.command if self.live_command else None,
            failures=failures,
            selected_task=self.selected_task(),
            head_worker=self.head_worker(),
        )

    # ----- rendering ---------------------------------------------------------

    def _tick(self) -> None:
        if self.live_command is not None:
            self._frame += 1
            self._render()

    def _render(self) -> None:
        if not self._view_ready:
            return
        self.pipeline = evaluate(self._inputs())
        live = self.live_command
        elapsed = time.monotonic() - live.started if live else None
        if self.app_status is not None:
            self.query_one("#header", Static).update(header_text(self.config, self.app_status, self.discovery.problem))
        for stage in self.pipeline.stages:
            box = self.query_one(f"#stage-{stage.id.value}", StageBox)
            key = self.pipeline.keys[box.spec.key] if box.spec else None
            box.show(stage, key, self._frame, elapsed, stage.id is self.stage_focus)
        self._render_lists()
        self._render_evidence()
        self._render_log()
        self.query_one("#status", Static).update(self.status_text)
        self.query_one("#keys", Static).update(keybar_text(self.pipeline.keys, KEYS))

    def _render_lists(self) -> None:
        entries = []
        for ref in self.run_refs:
            if ref.run_id not in self.views:
                continue
            view = self.views[ref.run_id][1]
            token = run_token(view, self._show_for(ref.run_id))
            entries.append((token, ref.run_id, run_label(view.kind)))
        ids = [ref.run_id for ref in self.run_refs if ref.run_id in self.views]
        selected = ids.index(self.selected_run) if self.selected_run in ids else 0
        self.query_one("#runs", ListPanel).show(entries, selected)
        task_entries = [(Token.IDLE, task.name, "rework" if task.rework else "") for task in self.tasks]
        self.query_one("#task-list", ListPanel).show(task_entries, self.task_index)

    def _render_evidence(self) -> None:
        stage = self.pipeline.stage(self.stage_focus)
        task = None
        if self.stage_focus is StageId.TASK and self.selected_task() is not None:
            ref = self.selected_task()
            try:
                body = ref.path.read_text(errors="replace")
            except OSError as error:
                body = f"cannot read {ref.path}: {error}"
            task = (ref, body)
        self.query_one("#evidence", Static).update(evidence_text(stage, self.selected_view(), task))
        self.query_one("#evidence-scroll").border_title = f"Evidence · {stage.id.title}"

    def _render_log(self) -> None:
        panel = self.query_one("#log-tail", Static)
        out = Text(no_wrap=True, overflow="ellipsis")
        live = self.live_command
        if live is not None:
            elapsed = time.monotonic() - live.started
            out.append(f"{SPINNER[self._frame % len(SPINNER)]} {live.label()}  {elapsed:.0f}s\n", TOKEN_STYLE[Token.LIVE])
            lines = self._live_tail()
        elif self.finished is not None:
            token = Token.PROVEN if self.finished.exit_code == 0 else Token.FAILED
            out.append(f"{glyph(token)} {self.finished.label}  exit {self.finished.exit_code}\n", TOKEN_STYLE[token])
            lines = list(self.finished.lines[-TAIL_LINES:])
        else:
            out.append("No command has run in this session.\n", "dim")
            lines = []
        for line in lines[-TAIL_LINES:]:
            out.append(line + "\n", "dim")
        out.rstrip()
        panel.update(out)

    def _live_tail(self) -> list[str]:
        live = self.live_command
        lab = self.config.lab
        files = [*lab.glob("runs/*/logs/worker.log"), *lab.glob("runs/*/*/logs/worker.log")]
        fresh = []
        for path in files:
            try:
                stamp = path.stat().st_mtime_ns
            except OSError:
                continue
            if stamp >= live.started_ns:
                fresh.append((stamp, path))
        if fresh:
            return tail_of(max(fresh)[1], TAIL_LINES)
        return list(live.lines)[-TAIL_LINES:]

    def set_status(self, message: str, token: Token = Token.IDLE) -> None:
        self.status_text = Text(f"{glyph(token)} {message}" if token is not Token.IDLE else message, style=TOKEN_STYLE[token])
        if self._view_ready:
            self.query_one("#status", Static).update(self.status_text)

    # ----- actions -----------------------------------------------------------

    def _main_screen_active(self) -> bool:
        return len(self.screen_stack) <= 1

    def focus_stage(self, stage_id: StageId) -> None:
        self.stage_focus = stage_id
        self._render()

    def action_move_stage(self, step: int) -> None:
        if not self._main_screen_active():
            return
        index = max(0, min(len(PIPELINE) - 1, PIPELINE.index(self.stage_focus) + step))
        self.focus_stage(PIPELINE[index])

    def action_move_task(self, step: int) -> None:
        if self._main_screen_active() and self.tasks:
            self.task_index = (self.task_index + step) % len(self.tasks)
            self._render()

    def action_preview_task(self) -> None:
        if self._main_screen_active():
            self.focus_stage(StageId.TASK)

    def action_cycle_run(self, step: int) -> None:
        if not self._main_screen_active() or not self.run_refs:
            return
        ids = [ref.run_id for ref in self.run_refs]
        index = ids.index(self.selected_run) if self.selected_run in ids else 0
        self.selected_run = ids[(index + step) % len(ids)]
        self._render()

    def action_scroll_evidence(self, direction: int) -> None:
        scroll = self.query_one("#evidence-scroll", VerticalScroll)
        scroll.scroll_page_down() if direction > 0 else scroll.scroll_page_up()

    def action_quit_app(self) -> None:
        if not self._main_screen_active():
            return
        if self.live_command is not None and not self._quit_armed:
            self._quit_armed = True
            self.set_status(f"{self.live_command.label()} is still running. Press q again to stop it and quit.", Token.BLOCKED)
            return
        self.backend.terminate()
        self.exit()

    def action_toggle_log(self) -> None:
        if self._main_screen_active():
            title, body = self.full_log()
            self.push_screen(LogScreen(title, body))

    def full_log(self) -> tuple[str, str]:
        stage_id = self.stage_focus
        run = self.selected_view()
        parts: list[str] = []
        if run is not None and stage_id is StageId.WORKER:
            failed = self.pipeline is not None and self.pipeline.stage(StageId.WORKER).token is Token.FAILED
            if failed and run.last_brief is not None:
                files = [run.last_brief]
            else:
                files = [run.worker_dir / "logs" / "worker.log"]
            parts += [f"== {path.relative_to(run.path)} ==\n{read_tail_text(path)}" for path in files if path.is_file()]
        if self.live_command is not None:
            parts.append(f"== running: {self.live_command.label()} ==\n" + "\n".join(self.live_command.lines))
        elif self.finished is not None:
            parts.append(f"== last command: {self.finished.label} (exit {self.finished.exit_code}) ==\n" + "\n".join(self.finished.lines))
        title = f"Log · {stage_id.title}" + (f" · {run.run_id}" if run else "")
        return title, "\n\n".join(parts) or "No log files for this stage and no command has run in this session."

    def action_launch(self, key: str) -> None:
        if not self._main_screen_active():
            return
        spec = SPEC_BY_KEY[key]
        if self.live_command is not None:
            self.set_status(
                f"{self.live_command.label()} is still running. One command at a time; {spec.label} not started.",
                Token.BLOCKED,
            )
            return
        state = self.pipeline.keys[key]
        if state.token is Token.DARK:
            self.set_status(f"{spec.label}: {state.reason}", Token.BLOCKED)
            return
        if state.token is Token.BLOCKED:
            self.set_status(f"{spec.label} is blocked: {state.reason}", Token.BLOCKED)
            return
        args = self._arguments(spec)
        if args is None:
            self.set_status(f"{spec.label} needs a task or a run", Token.BLOCKED)
            return
        self.start(spec.command, args)

    def _arguments(self, spec: KeySpec) -> tuple[str, ...] | None:
        run, task = self.selected_view(), self.selected_task()
        if spec.command in (Command.WORK, Command.RUN):
            return (f"tasks/{task.name}.md",) if task else None
        if spec.command is Command.RECORD:
            source = self.head_worker()
            if source is None or source.worker is None:
                return None
            return (source.worker.task, f"runs/{source.run_id}")
        return (run.run_id,) if run else None

    def start(self, command: Command, args: tuple[str, ...]) -> None:
        run_scoped = command not in RUN_STARTERS
        live = LiveCommand(
            command, args, self.selected_run if run_scoped else None, time.monotonic(), time.time_ns() - 50_000_000
        )
        self.live_command = live
        self._quit_armed = False
        self.set_status(f"started {live.label()}", Token.LIVE)
        self._render()
        self._command_task = asyncio.create_task(self._drive(live))

    async def _drive(self, live: LiveCommand) -> None:
        result: CommandResult | None = None
        try:
            result = await self.backend.run_command(live.command, live.args, live.lines.append)
        finally:
            self.live_command = None
            if result is not None:
                await self._finish(live, result)
            else:
                self._render()

    async def _finish(self, live: LiveCommand, result: CommandResult) -> None:
        done = result.completed
        self.finished = Finished(live.label(), done.exit_code, result.reason, tuple(live.lines))
        key = (live.run_id, live.command)
        if result.ok:
            self.failures.pop(key, None)
            self.set_status(f"{live.label()} finished, exit 0", Token.PROVEN)
        else:
            self.failures[key] = result.reason
            self.set_status(f"{live.label()} exit {done.exit_code}: {result.reason}", Token.FAILED)
        if live.run_id is not None:
            self.shows.pop(live.run_id, None)
        await self._discover_if_changed(force=True)
        self._scan()
        if live.command in RUN_STARTERS:
            self._adopt_new_run(live, done.stdout)
        await self.refresh_now()

    def _adopt_new_run(self, live: LiveCommand, stdout: tuple[str, ...]) -> None:
        printed = next((line.strip() for line in reversed(stdout) if line.strip()), "")
        if printed and (self.config.lab / "runs" / printed).is_dir():
            self.selected_run = printed
            self.shows.pop(printed, None)
            return
        fresh = [ref for ref in self.run_refs if ref.mtime_ns >= live.started_ns]
        if fresh:
            self.selected_run = fresh[0].run_id

    async def wait_idle(self) -> None:
        if self._command_task is not None:
            await self._command_task


def read_tail_text(path: Path, limit: int = 200_000) -> str:
    try:
        return path.read_bytes()[-limit:].decode(errors="replace")
    except OSError as error:
        return f"cannot read {path}: {error}"


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(
            "usage: uv run factory-ui\n\n"
            "Run from the lab directory (or set FACTORY_LAB_DIR). Reads factory.py and runs/, tasks/.\n"
            "Environment: FACTORY_LAB_DIR, EXCALIDRAW_DIR, FACTORY_MODEL.\n"
            "Keys: w work, v review, j judge, d decide, r record, R recover, s resume, g run,\n"
            "      [ ] cycle runs, arrows move stage and task, enter preview task, l log, q quit."
        )
        return 0
    config = Config.from_env(os.environ, Path.cwd())
    FactoryApp(config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
