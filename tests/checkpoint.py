#!/usr/bin/env python3
"""Black-box factory contracts. Local substitutes only; no Bedrock or Yarn calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

LAB = Path(__file__).resolve().parents[1]
NAMES = ("install", "typecheck", "code", "other", "build", "diagram-audit")
SEATS = ("intent", "failure-modes", "operability")


def module(number):
    def decorate(function):
        function.module = number
        return function
    return decorate


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


WORKER = '''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
repo, task, logs = map(pathlib.Path, sys.argv[1:4])
brief = sys.argv[4]
assert all(p.is_absolute() for p in (repo, task, logs))
if brief:
    assert pathlib.Path(brief).is_absolute() and pathlib.Path(brief).is_file()
    assert "Changed paths" in pathlib.Path(brief).read_text()
assert pathlib.Path.cwd() == repo
with open(os.environ["WORKER_CALLS"], "a") as calls:
    calls.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
with (logs / "worker.log").open("a") as log: log.write("local checkpoint worker\\n")
if os.environ.get("WORKER_FAIL") == "1": sys.exit(7)
if os.environ.get("WORKER_NO_COMMIT") != "1":
    path = repo / os.environ.get("WORKER_PATH", "source.ts")
    path.write_text((path.read_text() if path.exists() else "") + "worker change\\n")
    subprocess.run(["git", "add", str(path)], check=True)
    subprocess.run(["git", "commit", "-qm", "checkpoint worker"], check=True)
'''

CHECKER = '''#!/usr/bin/env python3
import os, pathlib, subprocess, sys
verify, logs = map(pathlib.Path, sys.argv[1:3])
assert verify.is_absolute() and logs.is_absolute()
assert subprocess.check_output(["git", "status", "--porcelain"], cwd=verify) == b""
counter = pathlib.Path(os.environ["CHECKER_CALLS"])
count = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(count))
failed = os.environ.get("FAILED_CHECK", "build" if count <= int(os.environ.get("CHECKER_FAIL_ATTEMPTS", "0")) else "")
logs.mkdir(parents=True, exist_ok=True)
for name in ("install", "typecheck", "code", "other", "build", "diagram-audit"):
    if name == os.environ.get("MISSING_LOG"): continue
    (logs / (name + ".log")).write_text("local checkpoint check: " + name + "\\n" + "".join(f"line {i}\\n" for i in range(50)))
    (logs / (name + ".exit")).write_text("1" if name == failed else "0")
sys.exit(3 if os.environ.get("CHECKER_FAIL") == "1" else 0)
'''

REVIEWER = '''#!/usr/bin/env python3
import json, os, pathlib, sys
verify, logs, seat, output, prompt = sys.argv[1:6]
assert all(pathlib.Path(p).is_absolute() for p in (verify, logs, output, prompt))
state = json.loads((pathlib.Path(output).parents[1] / "state.json").read_text())
with open(os.environ["REVIEW_CALLS"], "a") as calls: calls.write(seat + "\\n")
text = pathlib.Path(prompt).read_text()
assert "checkpoint request" in text or "Filter Audit" in text
assert state["candidate_revision"] in text and state["check"]["evidence_hash"] in text
if os.environ.get("MISSING_REVIEW") == seat: sys.exit(0)
data = {"reviewer": seat, "candidate_revision": state["candidate_revision"],
        "evidence_hash": state["check"]["evidence_hash"],
        "decision": "rework" if seat in os.environ.get("REWORK_SEATS", "").split(",") else "approve",
        "reason": "local checkpoint review", "claims": [{"path": "source.ts", "note": "Known candidate change"}]}
if os.environ.get("STALE_REVIEW") == seat: data["candidate_revision"] = "0" * 40
if os.environ.get("MALFORMED_SEAT") == seat: data["claims"] = [{"path": "outside.ts", "note": "invalid claim"}]
pathlib.Path(output).write_text(json.dumps(data))
'''

JUDGE = '''#!/usr/bin/env python3
import hashlib, json, os, pathlib, re, sys
run, output, prompt = map(pathlib.Path, sys.argv[1:])
assert all(p.is_absolute() for p in (run, output, prompt))
state = json.loads((run / "state.json").read_text())
assert "quorum" in state
text = prompt.read_text()
assert state["candidate_revision"] in text and state["check"]["evidence_hash"] in text
with open(os.environ["JUDGE_CALLS"], "a") as calls: calls.write(run.name + "\\n")
decision = os.environ.get("JUDGE_DECISION", "approve" if state["quorum"]["passed"] else "rework")
if os.environ.get("JUDGE_APPROVE_ON_FAILED_QUORUM") == "1": decision = "approve"
brief = None
if decision == "rework":
    brief = {"failed_seats": [seat for seat, vote in state["reviews"].items() if vote["decision"] == "rework"],
             "excerpts": ["Repair the behavior described by the dissenting seats."],
             "base_revision": state["base_revision"], "candidate_revision": state["candidate_revision"],
             "allowed_paths": state["changed_paths"],
             "budget_remaining": int(re.search(r"Required budget_remaining for rework: (\\d+)", text)[1])}
if "JUDGE_BRIEF" in os.environ: brief = json.loads(os.environ["JUDGE_BRIEF"])
review_hash = hashlib.sha256(json.dumps(state["reviews"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
data = {"candidate_revision": state["candidate_revision"], "evidence_hash": state["check"]["evidence_hash"],
        "review_hash": review_hash, "decision": decision, "reason": "local checkpoint judgement", "brief": brief}
pathlib.Path(output).write_text(json.dumps(data))
'''

YARN = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["YARN_CALLS"], "a") as calls:
    calls.write(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd()}) + "\\n")
print("local checkpoint Yarn substitute")
sys.exit(4 if "test:typecheck" in sys.argv else 0)
'''


class FactoryContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="factory-contract-")
        self.addCleanup(self.temp.cleanup)
        # Resolve symlinks (macOS /var -> /private/var) so paths match what Git and the factory report.
        self.root = Path(self.temp.name).resolve()
        self.lab = self.root / "factory-lab"
        shutil.copytree(LAB, self.lab, ignore=shutil.ignore_patterns(
            ".git", "runs", "tests", "specs", "__pycache__", ".venv", ".opencode"))
        self.repo = self.root / "application"
        self.repo.mkdir()
        tools = self.root / "tools"
        tools.mkdir()
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(("FACTORY_", "WORKER_", "CHECKER_", "JUDGE_", "GIT_", "REWORK_"))}
        self.env.update({"PATH": str(tools) + os.pathsep + os.environ["PATH"],
                         "EXCALIDRAW_DIR": str(self.repo),
                         "GIT_AUTHOR_NAME": "Checkpoint", "GIT_AUTHOR_EMAIL": "test@example.test",
                         "GIT_COMMITTER_NAME": "Checkpoint", "GIT_COMMITTER_EMAIL": "test@example.test",
                         "WORKER_CALLS": str(self.root / "worker.jsonl"),
                         "CHECKER_CALLS": str(self.root / "checker.txt"),
                         "JUDGE_CALLS": str(self.root / "judge.txt"),
                         "REVIEW_CALLS": str(self.root / "review.txt"),
                         "YARN_CALLS": str(self.root / "yarn.jsonl")})
        for name, source in (("worker", WORKER), ("checker", CHECKER), ("reviewer", REVIEWER), ("judge", JUDGE), ("yarn", YARN)):
            script = tools / name
            script.write_text(source)
            script.chmod(0o755)
        self.env.update({"FACTORY_WORKER": str(tools / "worker"), "FACTORY_CHECKER": str(tools / "checker"),
                         "FACTORY_REVIEWER": str(tools / "reviewer"), "FACTORY_JUDGE": str(tools / "judge")})
        self.git("init", "-q")
        (self.repo / "source.ts").write_text("baseline\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.base = self.git("rev-parse", "HEAD")
        (self.repo / "source.ts").write_text("candidate\n")
        self.git("commit", "-qam", "candidate")
        self.candidate = self.git("rev-parse", "HEAD")
        self.policy = {"base_revision": self.base, "max_changed_files": 8,
                       "required_reviewers": 3, "required_approvals": 2}
        (self.lab / "policy.json").write_text(json.dumps(self.policy))
        (self.lab / "tasks").mkdir(exist_ok=True)
        self.request = self.lab / "tasks" / "request.md"
        self.request.write_text("checkpoint request\n")

    def execute(self, *args, expected=0, cwd=None, timeout=30):
        completed = subprocess.run(args, cwd=cwd or self.root, env=self.env,
                                   text=True, capture_output=True, timeout=timeout)
        detail = f"{args}\nstdout: {completed.stdout}\nstderr: {completed.stderr}"
        if expected == "failure":
            self.assertNotEqual(completed.returncode, 0, detail)
        elif expected is not None:
            self.assertEqual(completed.returncode, expected, detail)
        return completed

    def git(self, *args):
        return self.execute("git", *args, cwd=self.repo).stdout.strip()

    def cli(self, *args, **kwargs):
        return self.execute(sys.executable, str(self.lab / "factory.py"), *args, **kwargs)

    def shell(self, name, *args, **kwargs):
        return self.execute("bash", str(self.lab / name), *map(str, args), **kwargs)

    def calls(self, variable="WORKER_CALLS"):
        file = Path(self.env[variable])
        return file.read_text().splitlines() if file.exists() else []

    def record(self, expected=0):
        self.cli("work", str(self.request))
        self.candidate = self.git("rev-parse", "HEAD")
        before = len(self.calls())
        result = self.cli("record", str(self.request), expected=expected)
        self.assertEqual(len(self.calls()), before, "record must not run a worker")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.candidate)
        run_id = result.stdout.strip()
        self.assertEqual(len(run_id.splitlines()), 1, result.stdout)
        self.assertTrue((self.lab / "runs" / run_id / "state.json").is_file())
        return run_id

    def state(self, run_id):
        return json.loads(self.cli("show", run_id).stdout)

    def ready_for_decision(self):
        run_id = self.record()
        self.cli("review", run_id)
        self.cli("judge", run_id)
        return run_id

    @module(20)
    def test_worker_contract_and_log(self):
        self.cli("work", "tasks/request.md", "runs/one")
        call = json.loads(self.calls()[0])
        self.assertEqual(call["cwd"], str(self.repo))
        self.assertEqual(call["args"], [str(self.repo), str(self.request), str(self.lab / "runs/one/logs"), ""])
        self.assertIn("local checkpoint", (self.lab / "runs/one/logs/worker.log").read_text())
        self.assertNotEqual(self.git("rev-parse", "HEAD"), self.candidate)
        self.assertEqual(self.git("status", "--porcelain"), "")
        result = json.loads((self.lab / "runs/one/worker.json").read_text())
        self.assertEqual(set(result), {"task", "base_revision", "candidate_revision", "exit", "model", "attempts"})
        self.assertEqual(result["exit"], 0)
        self.assertEqual(result["base_revision"], self.base)
        self.assertEqual(result["candidate_revision"], self.git("rev-parse", "HEAD"))
        self.assertEqual(result["attempts"], [{"attempt": 1, "candidate_revision": result["candidate_revision"],
                                             "checker_exit": 0, "failed": []}])
        evidence = json.loads((self.lab / "runs/one/check.json").read_text())
        self.assertEqual(evidence["evidence_hash"], digest(evidence["proof"]))
        self.assertEqual(evidence["proof"]["changed_paths"], ["source.ts"])
        self.assertEqual(evidence["proof"]["verify_head"], result["candidate_revision"])
        self.assertTrue(evidence["proof"]["verify_clean"])
        self.assertEqual([entry["name"] for entry in evidence["proof"]["commands"]], list(NAMES))
        self.assertFalse((self.lab / "runs/one/verify").exists())
        self.assertEqual(len(self.git("worktree", "list", "--porcelain").split("worktree ")) - 1, 1)
        first = self.cli("work", "tasks/request.md").stdout.strip()
        second = self.cli("work", "tasks/request.md").stdout.strip()
        self.assertNotEqual(first, second)
        self.assertTrue((self.lab / "runs" / first / "worker.json").is_file())

    @module(20)
    def test_worker_rejects_dirty_missing_and_reused_outputs(self):
        self.cli("work", "tasks/missing.md", expected="failure")
        (self.repo / "source.ts").write_text("dirty\n")
        self.cli("work", "tasks/request.md", expected="failure")
        self.assertEqual(self.calls(), [])
        self.git("restore", "source.ts")
        self.cli("work", "tasks/request.md", "runs/one")
        log = (self.lab / "runs/one/logs/worker.log").read_bytes()
        self.cli("work", "tasks/request.md", "runs/one", expected="failure")
        self.assertEqual((self.lab / "runs/one/logs/worker.log").read_bytes(), log)
        self.assertEqual(len(self.calls()), 1)

    @module(20)
    def test_worker_preserves_failure_and_requires_commit(self):
        self.env["WORKER_FAIL"] = "1"
        self.cli("work", str(self.request), expected="failure")
        self.assertEqual(self.git("rev-parse", "HEAD"), self.candidate)
        self.env.pop("WORKER_FAIL")
        self.env["WORKER_NO_COMMIT"] = "1"
        self.cli("work", str(self.request), expected="failure")
        self.assertEqual(len(self.calls()), 2)
        self.assertFalse(Path(self.env["CHECKER_CALLS"]).exists())
        self.assertEqual(len(list((self.lab / "runs").rglob("worker.log"))), 2)
        for path in (self.lab / "runs").glob("*/worker.json"):
            self.assertNotEqual(json.loads(path.read_text())["exit"], 0)
            self.assertEqual(len(json.loads(path.read_text())["attempts"]), 1)

    @module(20)
    def test_failed_attempt_retries_from_brief_and_retains_evidence(self):
        self.env["CHECKER_FAIL_ATTEMPTS"] = "1"
        run_id = self.cli("work", str(self.request)).stdout.strip()
        output = self.lab / "runs" / run_id
        result = json.loads((output / "worker.json").read_text())
        self.assertEqual(result["exit"], 0)
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["attempts"][0]["failed"], ["build"])
        self.assertEqual(result["attempts"][1]["failed"], [])
        self.assertEqual(result["candidate_revision"], self.git("rev-parse", "HEAD"))
        self.assertEqual(self.git("rev-parse", "HEAD^"), result["attempts"][0]["candidate_revision"])
        archive = output / "attempts/1"
        for name in ("logs/build.log", "logs/build.exit", "logs/worker.log", "check.json", "worker.log", "brief.md"):
            self.assertTrue((archive / name).is_file(), name)
        brief = (archive / "brief.md").read_text()
        self.assertIn("build", brief)
        self.assertIn("source.ts", brief)
        self.assertIn("line 10\n", brief)
        self.assertIn("line 49\n", brief)
        self.assertNotIn("line 9\n", brief)
        self.assertEqual(json.loads(self.calls()[1])["args"][3], str(archive / "brief.md"))
        self.assertEqual((output / "logs/build.exit").read_text(), "0")

    @module(20)
    def test_three_failed_attempts_keep_last_candidate_and_final_evidence(self):
        self.env["CHECKER_FAIL_ATTEMPTS"] = "3"
        run_id = self.cli("work", str(self.request), expected="failure").stdout.strip()
        output = self.lab / "runs" / run_id
        result = json.loads((output / "worker.json").read_text())
        self.assertNotEqual(result["exit"], 0)
        self.assertEqual(len(self.calls()), 3)
        self.assertEqual([entry["attempt"] for entry in result["attempts"]], [1, 2, 3])
        self.assertEqual(result["candidate_revision"], self.git("rev-parse", "HEAD"))
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(sorted(path.name for path in (output / "attempts").iterdir()), ["1", "2"])
        self.assertEqual((output / "logs/build.exit").read_text(), "1")
        self.assertIn("build", (output / "brief.md").read_text())
        self.assertEqual(json.loads((output / "check.json").read_text())["proof"]["candidate_revision"], result["candidate_revision"])

    @module(20)
    def test_loop_order_fresh_sessions_and_stop(self):
        for name in ("unbound-arrows", "diagram-audit"):
            (self.lab / "tasks" / f"{name}.md").write_text("checkpoint request " + name)
        self.cli("loop")
        calls = [json.loads(line) for line in self.calls()]
        self.assertEqual(len(calls), 2)
        self.assertIn("unbound-arrows", " ".join(calls[0]["args"]))
        self.assertIn("diagram-audit", " ".join(calls[1]["args"]))
        self.assertEqual(len(list((self.lab / "runs").rglob("worker.log"))), 2)
        self.env["WORKER_FAIL"] = "1"
        self.cli("loop", expected="failure")
        self.assertEqual(len(self.calls()), 3)

    @module(20)
    def test_command_discovery_and_usage(self):
        commands = self.cli().stdout.splitlines()
        self.assertEqual(commands[:2], ["work", "loop"])
        self.assertEqual(len(commands), len(set(commands)))
        self.assertNotIn("check", commands)
        self.cli("check", "unused", expected=2)
        self.assertIn("usage:", self.cli("unknown", expected=2).stderr)
        self.cli("work", expected=2)

    @module(30)
    def test_record_identity_hashes_and_snapshots(self):
        run_id = self.record()
        state = self.state(run_id)
        self.assertEqual(state["run_id"], run_id)
        self.assertEqual(state["repo"], str(self.repo))
        self.assertEqual(state["candidate_revision"], self.candidate)
        self.assertEqual(state["base_revision"], self.base)
        self.assertEqual(state["changed_paths"], ["source.ts"])
        self.assertEqual(state["policy"], self.policy)
        self.assertEqual(state["policy_hash"], digest(self.policy))
        self.assertEqual(state["request_hash"], hashlib.sha256(self.request.read_bytes()).hexdigest())
        keys = ("run_id", "repo", "request", "request_hash", "policy", "policy_hash",
                "base_revision", "candidate_revision", "changed_paths")
        self.assertEqual(state["record_hash"], digest({key: state[key] for key in keys}))
        self.request.write_text("new request\n")
        (self.lab / "policy.json").write_text("{}")
        self.git("commit", "--allow-empty", "-qm", "later commit")
        self.assertEqual(self.state(run_id), state)
        self.assertEqual(Path(state["request"]).read_text(), "checkpoint request\n")
        self.assertEqual(len(self.calls()), 1)

    @module(30)
    def test_record_copies_worker_evidence_and_show_detects_edited_log(self):
        self.env["CHECKER_FAIL_ATTEMPTS"] = "1"
        worker_id = self.cli("work", str(self.request)).stdout.strip()
        source = self.lab / "runs" / worker_id
        run_id = self.cli("record", str(self.request), str(source)).stdout.strip()
        directory = self.lab / "runs" / run_id
        for path in source.rglob("*"):
            if path.is_file():
                self.assertEqual((directory / path.relative_to(source)).read_bytes(), path.read_bytes())
        self.assertEqual(self.state(run_id)["check"], json.loads((source / "check.json").read_text()))
        self.assertFalse((directory / "verify").exists())
        (directory / "logs/build.log").write_text("edited check\n")
        self.assertIn("evidence_hash", self.cli("show", run_id, expected="failure").stderr)

    @module(30)
    def test_record_requires_current_successful_worker(self):
        self.cli("record", str(self.request), expected="failure")
        worker_id = self.cli("work", str(self.request)).stdout.strip()
        source = self.lab / "runs" / worker_id
        self.git("commit", "--allow-empty", "-qm", "later candidate")
        self.assertIn("candidate_revision", self.cli("record", str(self.request), str(source), expected="failure").stderr)
        self.env["CHECKER_FAIL_ATTEMPTS"] = "99"
        worker_id = self.cli("work", str(self.request), expected="failure").stdout.strip()
        self.assertIn("worker exit", self.cli("record", str(self.request), str(self.lab / "runs" / worker_id), expected="failure").stderr)
        self.assertEqual(list((self.lab / "runs").glob("*/state.json")), [])

    @module(30)
    def test_record_unique_and_invalid_inputs(self):
        self.assertNotEqual(self.record(), self.record())
        (self.repo / "source.ts").write_text("dirty\n")
        self.cli("record", str(self.request), expected="failure")
        self.git("restore", "source.ts")
        (self.lab / "policy.json").write_text("{}")
        self.cli("record", str(self.request), expected="failure")
        self.cli("show", "../outside", expected="failure")
        self.cli("show", "missing", expected="failure")

    @module(30)
    def test_show_names_changed_record_and_request(self):
        run_id = self.record()
        path = self.lab / "runs" / run_id / "state.json"
        original = path.read_bytes()
        state = json.loads(original)
        state["candidate_revision"] = self.base
        path.write_text(json.dumps(state))
        self.assertIn("record_hash", self.cli("show", run_id, expected="failure").stderr)
        path.write_bytes(original)
        Path(state["request"]).write_text("edited request")
        self.assertIn("request_hash", self.cli("show", run_id, expected="failure").stderr)

    @module(40)
    def test_check_and_review_bind_to_saved_revision(self):
        run_id = self.record()
        self.git("commit", "--allow-empty", "-qm", "later commit")
        self.cli("review", run_id)
        state = self.state(run_id)
        self.assertEqual(state["status"], "reviewed")
        proof = state["check"]["proof"]
        self.assertEqual(proof["verify_head"], self.candidate)
        self.assertEqual(proof["candidate_revision"], self.candidate)
        self.assertEqual(state["check"]["evidence_hash"], digest(proof))
        self.assertEqual([entry["name"] for entry in proof["commands"]], list(NAMES))
        self.assertEqual(set(state["reviews"]), set(SEATS))
        self.assertEqual(self.calls("REVIEW_CALLS"), list(SEATS))
        self.cli("review", run_id)
        self.assertEqual(len(self.calls("REVIEW_CALLS")), 3)

    @module(40)
    def test_failed_command_blocks_reviews(self):
        run_id = self.record()
        directory = self.lab / "runs" / run_id
        state = self.state(run_id)
        (directory / "logs/build.exit").write_text("1")
        state["check"]["proof"]["commands"][4]["exit"] = 1
        state["check"]["evidence_hash"] = digest(state["check"]["proof"])
        (directory / "check.json").write_text(json.dumps(state["check"]))
        (directory / "state.json").write_text(json.dumps(state))
        self.cli("review", run_id, expected="failure")
        self.assertEqual(self.calls("REVIEW_CALLS"), [])

    @module(20)
    def test_failed_checker_with_success_logs_still_blocks(self):
        self.env["CHECKER_FAIL"] = "1"
        run_id = self.cli("work", str(self.request), expected="failure").stdout.strip()
        result = json.loads((self.lab / "runs" / run_id / "worker.json").read_text())
        self.assertNotEqual(result["exit"], 0)
        self.assertEqual([entry["checker_exit"] for entry in result["attempts"]], [3, 3, 3])
        self.assertEqual([entry["failed"] for entry in result["attempts"]], [[], [], []])

    @module(20)
    def test_missing_log_blocks(self):
        self.env["MISSING_LOG"] = "diagram-audit"
        result = self.cli("work", str(self.request), expected="failure")
        self.assertIn("diagram-audit.exit", result.stderr)
        self.assertFalse((self.lab / "runs" / result.stdout.strip() / "verify").exists())

    @module(20)
    def test_protected_configuration_blocks(self):
        self.env["WORKER_PATH"] = "package.json"
        result = self.cli("work", str(self.request), expected="failure")
        self.assertIn("protected paths: package.json", result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertFalse(Path(self.env["CHECKER_CALLS"]).exists())
        self.assertEqual(self.calls("REVIEW_CALLS"), [])

    @module(40)
    def test_changed_log_and_dirty_worktree_block_review(self):
        run_id = self.record()
        log = self.lab / "runs" / run_id / "logs/build.log"
        original = log.read_bytes()
        log.write_text("changed\n")
        self.cli("review", run_id, expected="failure")
        log.write_bytes(original)
        self.git("worktree", "add", "--detach", str(self.lab / "runs" / run_id / "verify"), self.candidate)
        (self.lab / "runs" / run_id / "verify/source.ts").write_text("dirty\n")
        self.cli("review", run_id, expected="failure")

    @module(40)
    def test_review_rejects_wrong_binding_and_partial_results(self):
        for variable in ("STALE_REVIEW", "MISSING_REVIEW", "MALFORMED_SEAT"):
            with self.subTest(variable=variable):
                run_id = self.record()
                self.env[variable] = "failure-modes"
                self.cli("review", run_id, expected="failure")
                self.env.pop(variable)
                self.cli("review", run_id, expected="failure")

    @module(20)
    def test_check_adapter_uses_real_commands(self):
        logs = self.root / "adapter-logs"
        self.shell("check-change.sh", self.repo, logs, expected="failure")
        calls = [json.loads(line) for line in self.calls("YARN_CALLS")]
        self.assertEqual([call["args"] for call in calls], [
            ["install", "--frozen-lockfile", "--non-interactive"], ["test:typecheck"],
            ["test:code"], ["test:other"], ["build:app"],
            ["vitest", "--run", "--passWithNoTests", "--minWorkers=1", "--maxWorkers=2",
             "packages/excalidraw/tests/diagramAudit.test.tsx"]])
        self.assertTrue(all(call["cwd"] == str(self.repo) for call in calls))
        self.assertEqual((logs / "typecheck.exit").read_text().strip(), "4")
        self.assertEqual(len(list(logs.glob("*.log"))), 6)

    @module(40)
    def test_quorum_pass_and_failed_approve_is_rejected_unsaved(self):
        for seats, passed in (("", True), ("intent", True), ("intent,failure-modes", False)):
            with self.subTest(seats=seats):
                self.env["REWORK_SEATS"] = seats
                run_id = self.record()
                self.cli("review", run_id)
                self.env["JUDGE_APPROVE_ON_FAILED_QUORUM"] = "1"
                result = self.cli("judge", run_id, expected=0 if passed else "failure")
                state = self.state(run_id)
                self.assertEqual(state["quorum"], {"required": 2, "approvals": 3 - len(seats.split(",")) if seats else 3,
                                 "votes": {seat: "rework" if seat in seats.split(",") else "approve" for seat in SEATS},
                                 "passed": passed})
                if passed:
                    self.assertEqual(state["judge"]["decision"], "approve")
                    self.assertEqual(state["judge"]["review_hash"], digest(state["reviews"]))
                else:
                    self.assertIn("quorum failed", result.stderr)
                    self.assertNotIn("judge", state)
                    self.assertFalse((self.lab / "runs" / run_id / "judge.json").exists())

    @module(40)
    def test_rework_task_and_budget_exhaustion(self):
        self.env["REWORK_SEATS"] = "intent,failure-modes"
        for remaining in (2, 1, 0):
            run_id = self.ready_for_decision()
            state = self.state(run_id)
            self.assertEqual(state["status"], "judged")
            self.assertEqual(state["judge"]["brief"]["budget_remaining"], remaining)
            self.assertEqual(sorted(state["judge"]["brief"]["failed_seats"]), ["failure-modes", "intent"])
            brief = self.lab / "runs" / run_id / "rework-brief.md"
            task = self.lab / "tasks" / f"rework-{run_id}.md"
            self.assertTrue(brief.is_file())
            self.assertEqual(task.exists(), remaining > 0)
            if remaining:
                self.assertIn("checkpoint request", task.read_text())
                self.assertIn(brief.read_text(), task.read_text())
                self.request = task

    @module(40)
    def test_judge_rework_requires_valid_bounded_brief(self):
        for change in ({"budget_remaining": 0}, {"allowed_paths": ["outside.ts"]},
                       {"excerpts": ["x" * 401]}, {"failed_seats": ["made-up"]}, {"failed_seats": ["build"]}):
            self.env["REWORK_SEATS"] = "intent"
            run_id = self.record()
            self.cli("review", run_id)
            state = self.state(run_id)
            brief = {"failed_seats": ["intent"], "excerpts": ["Repair the test"],
                     "base_revision": self.base, "candidate_revision": self.candidate,
                     "allowed_paths": ["source.ts"], "budget_remaining": 2, **change}
            self.env.update({"JUDGE_DECISION": "rework", "JUDGE_BRIEF": json.dumps(brief)})
            self.cli("judge", run_id, expected="failure")
            self.assertNotIn("judge", self.state(run_id))

    @module(40)
    def test_show_checks_every_saved_evidence_layer(self):
        run_id = self.ready_for_decision()
        directory = self.lab / "runs" / run_id
        for name in ("logs/build.log", "logs/code.exit", "reviews/intent.json", "judge.json", "candidate.diff", "check.json"):
            with self.subTest(name=name):
                path = directory / name
                original = path.read_bytes()
                path.write_text("changed")
                self.cli("show", run_id, expected="failure")
                path.write_bytes(original)
                self.cli("show", run_id)
        path = directory / "state.json"
        original = path.read_bytes()
        state = json.loads(original)
        state["quorum"]["passed"] = False
        path.write_text(json.dumps(state))
        self.assertIn("quorum", self.cli("show", run_id, expected="failure").stderr)
        path.write_bytes(original)

    @module(40)
    def test_review_reason_edit_is_not_normalized_away(self):
        run_id = self.ready_for_decision()
        path = self.lab / "runs" / run_id / "reviews/intent.json"
        vote = json.loads(path.read_text())
        vote["reason"] += " "
        path.write_text(json.dumps(vote))
        self.assertIn("saved vote mismatch", self.cli("show", run_id, expected="failure").stderr)

    @module(50)
    def test_ready_decision_is_stable_and_uses_policy_snapshot(self):
        run_id = self.ready_for_decision()
        (self.lab / "policy.json").write_text("{}")
        self.cli("decide", run_id)
        decision = self.state(run_id)["decision"]
        self.assertEqual(decision["status"], "ready")
        self.assertTrue(decision["reason"])
        self.assertEqual(decision["decision_hash"], digest({k: v for k, v in decision.items() if k != "decision_hash"}))
        self.cli("decide", run_id)
        self.assertEqual(self.state(run_id)["decision"], decision)
        (self.lab / "runs" / run_id / "logs/build.log").write_text("edited\n")
        self.cli("decide", run_id, expected="failure")
        self.assertEqual(json.loads((self.lab / "runs" / run_id / "state.json").read_text())["decision"], decision)

    @module(50)
    def test_reused_stages_preserve_terminal_status(self):
        (self.repo / "second.ts").write_text("second change\n")
        self.git("add", ".")
        self.git("commit", "-qm", "second path")
        for outcome in ("ready", "needs-rework", "needs-human"):
            with self.subTest(outcome=outcome):
                self.env["REWORK_SEATS"] = "intent,failure-modes" if outcome == "needs-rework" else ""
                self.policy["max_changed_files"] = 1 if outcome == "needs-human" else 8
                (self.lab / "policy.json").write_text(json.dumps(self.policy))
                run_id = self.ready_for_decision()
                expected = 0 if outcome == "ready" else "failure"
                self.cli("decide", run_id, expected=expected)
                original = self.state(run_id)
                self.assertEqual(original["status"], outcome)
                calls = self.calls("REVIEW_CALLS")
                for stage in ("review", "judge", "decide"):
                    self.cli(stage, run_id, expected=expected if stage == "decide" else 0)
                    self.assertEqual(self.state(run_id), original, f"{stage} changed completed state")
                self.assertEqual(self.calls("REVIEW_CALLS"), calls)

    @module(50)
    def test_rework_and_missing_review_cannot_be_ready(self):
        self.env["REWORK_SEATS"] = "intent,failure-modes"
        run_id = self.ready_for_decision()
        self.cli("decide", run_id, expected="failure")
        self.assertEqual(self.state(run_id)["decision"]["status"], "needs-rework")
        (self.lab / "runs" / run_id / "reviews/intent.json").unlink()
        self.cli("decide", run_id, expected="failure")

    @module(50)
    def test_broad_scope_needs_human(self):
        for number in range(9):
            (self.repo / f"source-{number}.ts").write_text("change\n")
        self.git("add", ".")
        self.git("commit", "-qm", "broad candidate")
        run_id = self.ready_for_decision()
        self.cli("decide", run_id, expected="failure")
        self.assertEqual(self.state(run_id)["decision"]["status"], "needs-human")

    @module(60)
    def test_stop_recover_and_resume_do_not_repeat_worker(self):
        self.env["FACTORY_STOP_AFTER_SAVE"] = "1"
        self.cli("run", str(self.request), expected="failure")
        records = list((self.lab / "runs").glob("*/state.json"))
        self.assertEqual(len(records), 1)
        run_id = records[0].parent.name
        original = self.state(run_id)
        self.assertEqual(original["status"], "recorded")
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls("REVIEW_CALLS"), [])
        self.env.pop("FACTORY_STOP_AFTER_SAVE")
        recovery = self.cli("recover", run_id, expected="failure")
        self.assertEqual(recovery.stdout.strip(), run_id)
        self.assertIn("review:", recovery.stderr)
        self.assertEqual(self.state(run_id), original)
        self.cli("resume", run_id)
        completed = self.state(run_id)
        self.assertEqual(completed["status"], "ready")
        self.assertEqual(completed["status"], completed["decision"]["status"])
        evidence = {path: path.read_bytes() for folder in ("logs", "reviews")
                    for path in (self.lab / "runs" / run_id / folder).iterdir() if path.is_file()}
        self.cli("resume", run_id)
        self.assertEqual(self.state(run_id), completed, "repeated resume changed completed state")
        self.assertEqual({path: path.read_bytes() for path in evidence}, evidence)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(len(self.calls("REVIEW_CALLS")), 3)
        self.assertEqual(len(self.calls("JUDGE_CALLS")), 1)
        self.assertEqual(len(list((self.lab / "runs").glob("*/state.json"))), 1)

        for outcome in ("needs-rework", "needs-human"):
            with self.subTest(outcome=outcome):
                self.env["REWORK_SEATS"] = "intent,failure-modes" if outcome == "needs-rework" else ""
                self.policy["max_changed_files"] = 1
                (self.lab / "policy.json").write_text(json.dumps(self.policy))
                if outcome == "needs-human":
                    (self.repo / "second.ts").write_text("second change\n")
                    self.git("add", ".")
                    self.git("commit", "-qm", "second path")
                other = self.record()
                self.cli("resume", other, expected="failure")
                final = self.state(other)
                self.assertEqual(final["status"], outcome)
                calls = self.calls("REVIEW_CALLS")
                self.cli("resume", other, expected="failure")
                self.assertEqual(self.state(other), final)
                self.assertEqual(self.calls("REVIEW_CALLS"), calls)

    @module(60)
    def test_run_carries_request_through_decision(self):
        self.cli("run", str(self.request))
        records = list((self.lab / "runs").glob("*/state.json"))
        self.assertEqual(len(records), 1)
        self.assertEqual(json.loads(records[0].read_text())["decision"]["status"], "ready")
        self.assertEqual(len(self.calls()), 1)

    @module(60)
    def test_worker_failure_stops_before_record(self):
        self.env["WORKER_FAIL"] = "1"
        self.cli("run", str(self.request), expected="failure")
        self.assertEqual(list((self.lab / "runs").glob("*/state.json")), [])
        self.assertEqual(self.calls("REVIEW_CALLS"), [])

    @module(60)
    def test_recovery_rejects_changed_identity(self):
        run_id = self.record()
        path = self.lab / "runs" / run_id / "state.json"
        state = json.loads(path.read_text())
        state["candidate_revision"] = self.base
        path.write_text(json.dumps(state))
        self.cli("recover", run_id, expected="failure")
        self.assertEqual(len(self.calls()), 1)

    @module(60)
    def test_recovery_names_first_invalid_stage_and_preserves_files(self):
        run_id = self.ready_for_decision()
        self.cli("decide", run_id)
        self.cli("recover", run_id)
        directory = self.lab / "runs" / run_id
        original = (directory / "state.json").read_bytes()
        (directory / "logs/build.log").write_text("changed check")
        (directory / "reviews/intent.json").write_text("changed vote")
        result = self.cli("recover", run_id, expected="failure")
        self.assertTrue(result.stderr.startswith("check:"), result.stderr)
        self.assertIn("run work again and record a new run", self.cli("resume", run_id, expected="failure").stderr)
        self.assertEqual((directory / "state.json").read_bytes(), original)
        self.assertEqual(len(self.calls("REVIEW_CALLS")), 3)
        self.assertEqual(len(self.calls("JUDGE_CALLS")), 1)

    @module(60)
    def test_recovery_names_malformed_saved_stage(self):
        run_id = self.ready_for_decision()
        path = self.lab / "runs" / run_id / "state.json"
        state = json.loads(path.read_text())
        state["reviews"]["intent"]["decision"] = "unknown"
        path.write_text(json.dumps(state))
        result = self.cli("recover", run_id, expected="failure")
        self.assertTrue(result.stderr.startswith("review:"), result.stderr)
        # Earlier damaged logs must win over malformed later JSON fields.
        (path.parent / "logs/build.log").write_text("changed check")
        result = self.cli("recover", run_id, expected="failure")
        self.assertTrue(result.stderr.startswith("check:"), result.stderr)
        state["candidate_revision"] = self.base
        path.write_text(json.dumps(state))
        result = self.cli("recover", run_id, expected="failure")
        self.assertTrue(result.stderr.startswith("record:"), result.stderr)

    @module(60)
    def test_resume_missing_or_malformed_check_requires_new_work(self):
        run_id = self.record()
        path = self.lab / "runs" / run_id / "state.json"
        original = json.loads(path.read_text())
        for check in (None, {"proof": {}}):
            state = {**original, "check": check}
            path.write_text(json.dumps(state))
            result = self.cli("resume", run_id, expected="failure")
            self.assertIn("run work again and record a new run", result.stderr)
            self.assertEqual(json.loads(path.read_text()), state)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls("REVIEW_CALLS"), [])

    @module(60)
    def test_recovery_names_quorum_before_judge(self):
        run_id = self.ready_for_decision()
        path = self.lab / "runs" / run_id / "state.json"
        state = self.state(run_id)
        state["quorum"]["passed"] = not state["quorum"]["passed"]
        state["judge"] = {}
        path.write_text(json.dumps(state))
        self.assertTrue(self.cli("recover", run_id, expected="failure").stderr.startswith("quorum:"))


def bedrock_smoke():
    """Explicit integration gate: the agent is real; the six-command checker is local."""
    case = FactoryContracts()
    try:
        case.setUp()
        case.env.pop("FACTORY_WORKER")
        case.env["FACTORY_MODEL"] = os.environ["FACTORY_MODEL"]
        case.request.write_text(
            "Create hello.py with greet(name) returning 'Hello, NAME!' using the supplied name. "
            "Add test_hello.py using Python unittest for an ordinary name and an empty name. "
            "Run PYTHONDONTWRITEBYTECODE=1 python -m unittest -v. Leave source.ts unchanged. "
            "Do not change dependencies or configuration. Commit hello.py and test_hello.py locally. "
            "Leave the checkout clean.\n")
        result = case.cli("work", str(case.request), expected=None, timeout=300)
        print(f"work exit: {result.returncode}\nstdout:\n{result.stdout}stderr:\n{result.stderr}", flush=True)
        output = case.lab / "runs" / result.stdout.strip()
        if (output / "worker.json").exists():
            print("worker.json:\n" + (output / "worker.json").read_text(), flush=True)
        if result.returncode:
            if (output / "logs/worker.log").exists():
                print((output / "logs/worker.log").read_text(), flush=True)
            return result.returncode
        print("Independent smoke assertions:", flush=True)
        test = case.execute(sys.executable, "-B", "-m", "unittest", "-v", cwd=case.repo)
        print(test.stdout + test.stderr, flush=True)
        case.assertEqual(case.git("status", "--porcelain"), "")
        case.assertNotEqual(case.git("rev-parse", "HEAD"), case.candidate)
        case.assertEqual(case.calls(), [], "smoke must not use the substitute worker")
        case.assertFalse((output / "verify").exists())
        return 0
    finally:
        case.doCleanups()


def main():
    global LAB
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", type=int, choices=(20, 30, 40, 50, 60))
    parser.add_argument("--lab", type=Path, default=LAB)
    parser.add_argument("--bedrock-smoke", action="store_true", help="Run one real worker on a disposable tiny repo")
    args = parser.parse_args()
    LAB = args.lab.resolve()
    reference = LAB.parents[2] / "reference/factory-lab"
    if not (LAB / "factory.py").exists() and (reference / "factory.py").is_file():
        LAB = reference
    required = ["factory.py", "check-change.sh"]
    if args.module >= 30:
        required += ["policy.json"]
    if args.module >= 40:
        required += ["reviews/judge.md", *(f"reviews/{seat}.md" for seat in SEATS)]
    missing = [name for name in required if not (LAB / name).is_file()]
    if missing:
        print("Implement this module with OpenCode first. Missing: " + ", ".join(missing), file=sys.stderr)
        return 1
    if args.bedrock_smoke:
        return bedrock_smoke()
    names = [name for name in unittest.defaultTestLoader.getTestCaseNames(FactoryContracts)
             if getattr(getattr(FactoryContracts, name), "module") <= args.module]
    print(f"Module {args.module}: {len(names)} cumulative checks with local substitutes; no real model calls.", flush=True)
    suite = unittest.TestSuite(FactoryContracts(name) for name in names)
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
