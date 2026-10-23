"""catch-up restores factory files from a tag. These tests use a small Git lab with fake tags."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from factory_ui.catch_up import main

CHECKPOINT = """import os, sys
print("checkpoint", sys.argv[1])
sys.exit(int(os.environ.get("CHECKPOINT_EXIT", "0")))
"""


def git(lab: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=lab, check=True, stdout=subprocess.PIPE, text=True).stdout


def write(lab: Path, relative: str, text: str) -> None:
    path = lab / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def lab(tmp_path, monkeypatch) -> Path:
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}.items():
        monkeypatch.setenv(key, value)
    lab = tmp_path / "lab"
    lab.mkdir()
    git(lab, "init", "-q", "-b", "main")
    write(lab, ".gitignore", "runs/\n")
    write(lab, "README.md", "starter\n")
    write(lab, "tests/checkpoint.py", CHECKPOINT)
    git(lab, "add", ".")
    git(lab, "commit", "-qm", "starter")
    git(lab, "tag", "starter")
    write(lab, "factory.py", "# finished factory\n")
    write(lab, "check-change.sh", "#!/bin/sh\n")
    write(lab, "policy.json", '{"base_revision": "tag"}\n')
    write(lab, "reviews/judge.md", "judge\n")
    git(lab, "add", ".")
    git(lab, "commit", "-qm", "gate")
    git(lab, "tag", "02-gate")
    git(lab, "reset", "-q", "--hard", "starter")
    monkeypatch.setenv("FACTORY_LAB_DIR", str(lab))
    return lab


def snapshot(lab: Path) -> dict[str, str]:
    return {str(p.relative_to(lab)): p.read_text() for p in lab.rglob("*") if p.is_file() and ".git" not in p.parts}


@pytest.mark.parametrize("argv", [[], ["99-nope"], ["03-policy"]])
def test_unknown_or_missing_tag_touches_nothing(lab, capsys, argv):
    write(lab, "README.md", "my edit\n")
    before = snapshot(lab)
    assert main(argv) != 0
    assert snapshot(lab) == before
    assert git(lab, "stash", "list") == ""
    err = capsys.readouterr().err
    assert ("does not exist" in err) if argv == ["03-policy"] else ("Remove the routine approval" in err)


def test_restore_stashes_keeps_policy_and_runs_checkpoint(lab, capfd):
    write(lab, "README.md", "my edit\n")
    write(lab, "policy.json", '{"base_revision": "mine"}\n')
    write(lab, "runs/r1/state.json", "{}\n")

    assert main(["02-gate"]) == 0

    assert (lab / "factory.py").read_text() == "# finished factory\n"
    assert (lab / "check-change.sh").is_file()
    assert (lab / "reviews/judge.md").read_text() == "judge\n"
    assert (lab / "policy.json").read_text() == '{"base_revision": "mine"}\n'
    assert (lab / "README.md").read_text() == "starter\n"
    assert (lab / "runs/r1/state.json").read_text() == "{}\n"
    assert "Factory before 02-gate" in git(lab, "stash", "list")
    out = capfd.readouterr().out
    assert "Kept your policy.json." in out
    assert "checkpoint 40" in out


def test_clean_lab_skips_the_stash_and_returns_the_checkpoint_status(lab, capfd, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_EXIT", "3")
    assert main(["02-gate"]) == 3
    assert git(lab, "stash", "list") == ""
    assert (lab / "policy.json").read_text() == '{"base_revision": "tag"}\n'
    assert "Nothing to stash." in capfd.readouterr().out
