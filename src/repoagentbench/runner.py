import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .agents import get_agent
from .events import EventLog
from .verify import VerifyResult, run_verify


VENV_DIR = ".venv-rab"
SCHEMA_VERSION = "1"
HARNESS_VERSION = "0.0.6"


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    task_path: Path
    agent_name: str
    pre_verify_passed: bool
    post_verify_passed: bool
    status: str
    duration_seconds: float


def run_one_task(task_path: Path, agent_name: str, out_dir: Path) -> RunResult:
    task_path = task_path.resolve()
    out_dir = out_dir.resolve()

    task_id = _sanitize_task_id(task_path.name)
    run_id = _build_run_id(task_id, agent_name)
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now(timezone.utc)
    started = time.time()

    base_commit = _read_base_commit(task_path)

    _write_manifest(run_dir, run_id, task_id, task_path, agent_name, base_commit, started_at)

    events_path = run_dir / "events.jsonl"
    with EventLog(events_path) as events:
        events.emit(
            "run.started",
            run_id=run_id,
            task_id=task_id,
            agent=agent_name,
            base_commit=base_commit,
        )

        goal = (task_path / "goal.md").read_text() if (task_path / "goal.md").exists() else ""

        workdir = run_dir / "workdir"
        shutil.copytree(
            task_path,
            workdir,
            ignore=shutil.ignore_patterns(".runs", "__pycache__", "*.pyc", ".pytest_cache", VENV_DIR),
        )
        events.emit("workdir.copied", path=str(workdir))

        events.emit("venv.bootstrap.started")
        venv_env = _bootstrap_venv(workdir, run_dir / "venv_bootstrap.log")
        events.emit("venv.bootstrap.finished", venv_path=str(workdir / VENV_DIR))

        events.emit("verify.started", phase="pre")
        pre = run_verify(workdir, run_dir / "pre_verify.log", env_overrides=venv_env)
        events.emit(
            "verify.finished",
            phase="pre",
            passed=pre.passed,
            returncode=pre.returncode,
            duration_seconds=pre.duration_seconds,
            timed_out=pre.timed_out,
        )

        events.emit("agent.started", agent=agent_name)
        agent = get_agent(agent_name)
        agent_result = agent.run(
            workdir=workdir,
            goal=goal,
            task_path=task_path,
            log_path=run_dir / "agent.log",
        )
        events.emit("agent.finished", agent=agent_name, result=agent_result)

        diff_path = run_dir / "diff.patch"
        diff_stats = _compute_diff(task_path, workdir, diff_path)
        events.emit("diff.captured", **diff_stats)

        events.emit("verify.started", phase="post")
        post = run_verify(workdir, run_dir / "post_verify.log", env_overrides=venv_env)
        events.emit(
            "verify.finished",
            phase="post",
            passed=post.passed,
            returncode=post.returncode,
            duration_seconds=post.duration_seconds,
            timed_out=post.timed_out,
        )

        duration = time.time() - started
        status, failure_stage, summary = _classify(pre, post)
        events.emit(
            "run.finished",
            status=status,
            failure_stage=failure_stage,
            duration_seconds=round(duration, 3),
        )

    _write_verification(run_dir, pre, post)
    _write_status(
        run_dir, run_id, task_id, task_path, agent_name,
        status, failure_stage, summary, duration, pre, post, agent_result,
    )

    return RunResult(
        run_id=run_id,
        run_dir=run_dir,
        task_path=task_path,
        agent_name=agent_name,
        pre_verify_passed=pre.passed,
        post_verify_passed=post.passed,
        status=status,
        duration_seconds=duration,
    )


def _sanitize_task_id(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._")
    return cleaned or "task"


def _build_run_id(task_id: str, agent_name: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid.uuid4().hex[:6]
    safe_agent = re.sub(r"[^A-Za-z0-9._-]+", "-", agent_name)
    return f"{ts}__{task_id}__{safe_agent}__{suffix}"


def _read_base_commit(task_path: Path) -> Optional[str]:
    task_json = task_path / "task.json"
    if not task_json.exists():
        return None
    try:
        return json.loads(task_json.read_text()).get("base_sha")
    except (ValueError, OSError):
        return None


def _bootstrap_venv(workdir: Path, log_path: Path) -> dict:
    """Create an isolated venv inside workdir and return env vars that point
    pip / python / pytest at it. Without this, `pip install -e .` from a task's
    verify.sh pollutes the system Python and breaks the harness itself."""
    venv_path = workdir / VENV_DIR
    bin_dir = venv_path / ("Scripts" if os.name == "nt" else "bin")

    create = subprocess.run(
        [sys.executable, "-m", "venv", "--clear", str(venv_path)],
        capture_output=True, text=True,
    )
    if create.returncode != 0:
        log_path.write_text(
            f"$ {sys.executable} -m venv {venv_path}\nreturncode: {create.returncode}\n\n"
            f"--- STDOUT ---\n{create.stdout}\n--- STDERR ---\n{create.stderr}\n"
        )
        raise RuntimeError(f"Failed to create venv at {venv_path}")

    pip = str(bin_dir / "pip")
    install = subprocess.run(
        [pip, "install", "--quiet", "--upgrade", "pip", "pytest"],
        capture_output=True, text=True,
    )
    log_path.write_text(
        f"$ python -m venv {venv_path}\nreturncode: {create.returncode}\n\n"
        f"$ {pip} install --upgrade pip pytest\nreturncode: {install.returncode}\n\n"
        f"--- STDOUT ---\n{install.stdout}\n--- STDERR ---\n{install.stderr}\n"
    )
    if install.returncode != 0:
        raise RuntimeError(f"Failed to bootstrap pip/pytest in venv at {venv_path}")

    parent_path = os.environ.get("PATH", "")
    return {
        "PATH": f"{bin_dir}{os.pathsep}{parent_path}",
        "VIRTUAL_ENV": str(venv_path),
        "PYTHONNOUSERSITE": "1",
    }


def _write_manifest(
    run_dir: Path, run_id: str, task_id: str, task_path: Path,
    agent_name: str, base_commit: Optional[str], started_at: datetime,
) -> None:
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "task_path": str(task_path),
        "agent": agent_name,
        "base_commit": base_commit,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "harness_version": HARNESS_VERSION,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def _compute_diff(original: Path, modified: Path, out: Path) -> dict:
    proc = subprocess.run(
        [
            "diff", "-ruN",
            "--exclude=__pycache__",
            "--exclude=*.pyc",
            "--exclude=.pytest_cache",
            f"--exclude={VENV_DIR}",
            "--exclude=.git",
            str(original), str(modified),
        ],
        capture_output=True,
        text=True,
    )
    out.write_text(proc.stdout)
    files_changed = sum(1 for line in proc.stdout.splitlines() if line.startswith("diff "))
    lines_added = sum(1 for line in proc.stdout.splitlines() if line.startswith("+") and not line.startswith("+++"))
    lines_removed = sum(1 for line in proc.stdout.splitlines() if line.startswith("-") and not line.startswith("---"))
    return {
        "files_changed": files_changed,
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


def _classify(pre: VerifyResult, post: VerifyResult) -> tuple[str, Optional[str], str]:
    if pre.timed_out:
        return ("FAIL", "pre_verify_timeout",
                f"Pre-verify timed out after {pre.duration_seconds}s before establishing a baseline.")
    if pre.passed:
        return ("INVALID_TASK", "pre_verify_unexpectedly_passed",
                "Pre-verify passed; this task does not establish a broken baseline "
                "(the agent has nothing to fix). Common causes: missing test patch, "
                "optional-dep skipif gating, or PR was a refactor/docs change.")
    if post.timed_out:
        return ("FAIL", "post_verify_timeout",
                f"Post-verify timed out after {post.duration_seconds}s; agent's changes did not converge.")
    if post.passed:
        return ("PASS", None,
                "Agent produced changes that pass the task's verification.")
    return ("FAIL", "post_verify",
            "Agent ran but verification still fails after its changes.")


def _write_verification(run_dir: Path, pre: VerifyResult, post: VerifyResult) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "phases": [
            {
                "phase": "pre",
                "command": pre.command,
                "passed": pre.passed,
                "exit_code": pre.returncode,
                "duration_seconds": pre.duration_seconds,
                "timed_out": pre.timed_out,
                "log": "pre_verify.log",
            },
            {
                "phase": "post",
                "command": post.command,
                "passed": post.passed,
                "exit_code": post.returncode,
                "duration_seconds": post.duration_seconds,
                "timed_out": post.timed_out,
                "log": "post_verify.log",
            },
        ],
    }
    (run_dir / "verification.json").write_text(json.dumps(payload, indent=2) + "\n")


def _write_status(
    run_dir: Path, run_id: str, task_id: str, task_path: Path, agent_name: str,
    status: str, failure_stage: Optional[str], summary: str,
    duration: float, pre: VerifyResult, post: VerifyResult, agent_result: dict,
) -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "task_path": str(task_path),
        "agent": agent_name,
        "status": status,
        "passed": (status == "PASS"),
        "failure_stage": failure_stage,
        "summary": summary,
        "duration_seconds": round(duration, 3),
        "pre_verify": {
            "passed": pre.passed,
            "returncode": pre.returncode,
            "duration_seconds": pre.duration_seconds,
        },
        "post_verify": {
            "passed": post.passed,
            "returncode": post.returncode,
            "duration_seconds": post.duration_seconds,
        },
        "agent_result": agent_result,
        "artifacts": {
            "manifest": "manifest.json",
            "events": "events.jsonl",
            "verification": "verification.json",
            "pre_verify": "pre_verify.log",
            "post_verify": "post_verify.log",
            "agent": "agent.log",
            "diff": "diff.patch",
            "workdir": "workdir/",
        },
    }
    (run_dir / "status.json").write_text(json.dumps(payload, indent=2) + "\n")
