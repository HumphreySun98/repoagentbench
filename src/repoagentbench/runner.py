import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .agents import get_agent
from .verify import run_verify


VENV_DIR = ".venv-rab"


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

    run_id = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    goal = (task_path / "goal.md").read_text()

    workdir = run_dir / "workdir"
    shutil.copytree(
        task_path,
        workdir,
        ignore=shutil.ignore_patterns(".runs", "__pycache__", "*.pyc", ".pytest_cache", VENV_DIR),
    )

    started = time.time()

    venv_env = _bootstrap_venv(workdir, run_dir / "venv_bootstrap.log")

    pre = run_verify(workdir, run_dir / "pre_verify.log", env_overrides=venv_env)

    agent = get_agent(agent_name)
    agent_result = agent.run(
        workdir=workdir,
        goal=goal,
        task_path=task_path,
        log_path=run_dir / "agent.log",
    )

    _compute_diff(task_path, workdir, run_dir / "diff.patch")

    post = run_verify(workdir, run_dir / "post_verify.log", env_overrides=venv_env)

    duration = time.time() - started

    if pre.passed:
        status = "INVALID_TASK"
    elif post.passed:
        status = "PASS"
    else:
        status = "FAIL"

    result = RunResult(
        run_id=run_id,
        run_dir=run_dir,
        task_path=task_path,
        agent_name=agent_name,
        pre_verify_passed=pre.passed,
        post_verify_passed=post.passed,
        status=status,
        duration_seconds=duration,
    )

    (run_dir / "status.json").write_text(json.dumps({
        "run_id": run_id,
        "task_path": str(task_path),
        "agent_name": agent_name,
        "pre_verify": {"passed": pre.passed, "returncode": pre.returncode},
        "post_verify": {"passed": post.passed, "returncode": post.returncode},
        "status": status,
        "duration_seconds": round(duration, 2),
        "agent_result": agent_result,
    }, indent=2))

    return result


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
        # Don't let user-site or PYTHONPATH leak the system's repoagentbench/click
        # back into the venv interpreter.
        "PYTHONNOUSERSITE": "1",
    }


def _compute_diff(original: Path, modified: Path, out: Path) -> None:
    proc = subprocess.run(
        [
            "diff", "-ruN",
            "--exclude=__pycache__",
            "--exclude=*.pyc",
            "--exclude=.pytest_cache",
            str(original), str(modified),
        ],
        capture_output=True,
        text=True,
    )
    out.write_text(proc.stdout)
