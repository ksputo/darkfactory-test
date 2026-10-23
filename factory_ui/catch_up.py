"""Restore the finished factory files from a catch-up tag, then run that module's checkpoint.

Uncommitted lab changes are stashed first. An existing policy.json is kept, because by
module 60 it holds the participant's own base_revision. runs/ is ignored by Git, so the
stash leaves saved runs alone.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from factory_ui.model import Config


@dataclass(frozen=True)
class Tag:
    module: int
    section: str
    files: tuple[str, ...]


BASE_FILES = ("factory.py", "check-change.sh")
TAGS = {
    "00-worker": Tag(20, "Run the worker loop", BASE_FILES),
    "01-record": Tag(30, "Save the candidate", (*BASE_FILES, "policy.json")),
    "02-gate": Tag(40, "Build the agentic gate", (*BASE_FILES, "policy.json", "reviews")),
    "03-policy": Tag(50, "Let a rule decide routine runs", (*BASE_FILES, "policy.json", "reviews")),
    "04-recovery": Tag(60, "Run and recover a task", (*BASE_FILES, "policy.json", "reviews")),
}


def usage() -> str:
    lines = ["usage: uv run catch-up TAG", "", "Tags:"]
    lines += [f"  {name:<12} module {tag.module}: {tag.section}" for name, tag in TAGS.items()]
    return "\n".join(lines)


def git(lab: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=lab, check=True, stdout=subprocess.PIPE, text=True).stdout


def tag_exists(lab: Path, name: str) -> bool:
    found = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{name}^{{commit}}"], cwd=lab, stdout=subprocess.DEVNULL)
    return found.returncode == 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in TAGS:
        print(usage(), file=sys.stderr)
        return 2
    name, tag = args[0], TAGS[args[0]]
    lab = Config.from_env(os.environ, Path.cwd()).lab
    if not tag_exists(lab, name):
        print(f"Tag {name} does not exist in {lab}. No files were restored.", file=sys.stderr)
        return 2

    policy = lab / "policy.json"
    kept = policy.read_bytes() if policy.is_file() else None
    if git(lab, "status", "--porcelain", "--untracked-files=all"):
        git(lab, "stash", "push", "--include-untracked", "-m", f"Factory before {name}")
        print(f"Stashed your changes: {git(lab, 'stash', 'list', '-1').strip()}")
    else:
        print("Nothing to stash.")
    try:
        git(lab, "restore", f"--source={name}", "--staged", "--worktree", "--", *tag.files)
        print(f"Restored from {name}: {', '.join(tag.files)}")
    finally:
        if kept is not None:
            policy.write_bytes(kept)
            print("Kept your policy.json.")

    return subprocess.run([sys.executable, "tests/checkpoint.py", str(tag.module)], cwd=lab).returncode


if __name__ == "__main__":
    raise SystemExit(main())
