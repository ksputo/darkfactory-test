"""The only module that starts subprocesses.

It runs `uv run factory.py <cmd>` for the pipeline and `git` read-only queries for
the application checkout. It never writes state, never hashes, never calls Bedrock.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .model import AppStatus, Command, Discovery, ShowResult, ShowStatus

QUERY_TIMEOUT_S = 60.0


@dataclass(frozen=True)
class Completed:
    exit_code: int
    stdout: tuple[str, ...]
    stderr: tuple[str, ...]

    @property
    def first_stderr(self) -> str:
        return next((line.strip() for line in self.stderr if line.strip()), "")


@dataclass(frozen=True)
class CommandResult:
    command: Command
    args: tuple[str, ...]
    completed: Completed

    @property
    def ok(self) -> bool:
        return self.completed.exit_code == 0

    @property
    def reason(self) -> str:
        return self.completed.first_stderr or f"exit {self.completed.exit_code}"


class Backend:
    def __init__(
        self,
        lab: Path,
        app: Path,
        runner: Sequence[str] = ("uv", "run"),
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.lab = lab
        self.app = app
        self.runner = tuple(runner)
        self.env = {**(os.environ if env is None else env), "PYTHONUNBUFFERED": "1"}
        self.started: list[tuple[Command, ...]] = []
        self._process: asyncio.subprocess.Process | None = None

    @property
    def factory_file(self) -> Path:
        return self.lab / "factory.py"

    async def _exec(
        self,
        argv: Sequence[str],
        cwd: Path,
        on_line: Callable[[str], None] | None = None,
        timeout: float | None = QUERY_TIMEOUT_S,
        track: bool = False,
    ) -> Completed:
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=self.env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            return Completed(127, (), (f"cannot start {argv[0]}: {error}",))
        if track:
            self._process = process
        out: list[str] = []
        err: list[str] = []

        async def pump(stream: asyncio.StreamReader, sink: list[str]) -> None:
            async for raw in stream:
                line = raw.decode(errors="replace").rstrip("\r\n")
                sink.append(line)
                if on_line is not None:
                    on_line(line)

        try:
            await asyncio.wait_for(
                asyncio.gather(pump(process.stdout, out), pump(process.stderr, err), process.wait()), timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            err.append(f"timed out after {timeout:.0f}s: {' '.join(argv)}")
            return Completed(124, tuple(out), tuple(err))
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        finally:
            if track:
                self._process = None
        return Completed(process.returncode or 0, tuple(out), tuple(err))

    def terminate(self) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()

    def _factory_argv(self, *args: str) -> list[str]:
        return [*self.runner, "factory.py", *args]

    async def discover(self) -> Discovery:
        if not self.factory_file.is_file():
            return Discovery.dark("factory.py not found")
        done = await self._exec(self._factory_argv(), self.lab)
        if done.exit_code != 0:
            return Discovery.dark(f"factory.py exit {done.exit_code}: {done.first_stderr or 'no stderr'}")
        return Discovery.parse("\n".join(done.stdout))

    async def show(self, run_id: str) -> ShowResult:
        done = await self._exec(self._factory_argv("show", run_id), self.lab)
        if done.exit_code == 0:
            return ShowResult(ShowStatus.OK)
        return ShowResult(ShowStatus.FAILED, done.first_stderr or f"show exit {done.exit_code}")

    async def run_command(
        self, command: Command, args: Sequence[str], on_line: Callable[[str], None]
    ) -> CommandResult:
        self.started.append((command, *args))
        done = await self._exec(self._factory_argv(command.value, *args), self.lab, on_line, timeout=None, track=True)
        return CommandResult(command, tuple(args), done)

    async def app_status(self) -> AppStatus:
        if not self.app.is_dir():
            return AppStatus(self.app, problem="not found")
        git = ["git", "-C", str(self.app)]
        head = await self._exec([*git, "log", "-1", "--format=%H %h"], self.lab)
        if head.exit_code != 0:
            return AppStatus(self.app, problem=head.first_stderr or "not a git checkout")
        revision, _, short = (head.stdout[0] if head.stdout else "").partition(" ")
        porcelain = await self._exec([*git, "status", "--porcelain"], self.lab)
        if porcelain.exit_code != 0:
            return AppStatus(self.app, head=short, revision=revision, problem=porcelain.first_stderr)
        dirty = any(line.strip() for line in porcelain.stdout)
        return AppStatus(self.app, head=short, revision=revision, dirty=dirty)
