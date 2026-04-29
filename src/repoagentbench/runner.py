import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .agents import get_agent
from .verify import run_verify


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
        ignore=shutil.ignore_patterns(".runs", "__pycache__", "*.pyc", ".pytest_cache"),
    )

    started = time.time()

    pre = run_verify(workdir, run_dir / "pre_verify.log")

    agent = get_agent(agent_name)
    agent_result = agent.run(
        workdir=workdir,
        goal=goal,
        task_path=task_path,
        log_path=run_dir / "agent.log",
    )

    _compute_diff(task_path, workdir, run_dir / "diff.patch")

    post = run_verify(workdir, run_dir / "post_verify.log")

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
