import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class VerifyResult:
    passed: bool
    returncode: int
    duration_seconds: float
    command: list[str] = field(default_factory=list)
    timed_out: bool = False


def run_verify(
    workdir: Path,
    log_path: Path,
    timeout: int = 600,
    env_overrides: Optional[dict] = None,
) -> VerifyResult:
    """Run task verification.

    Convention: if the task contains `verify.sh`, run it. Otherwise default to
    `python -m pytest` from whatever Python is first on PATH (the runner
    prepends a per-task venv so this resolves to the venv's interpreter).
    """
    verify_script = workdir / "verify.sh"
    if verify_script.exists():
        cmd = ["bash", str(verify_script)]
    else:
        cmd = ["python", "-m", "pytest", "-x", "--tb=short"]

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        duration = time.time() - started
        log_path.write_text(
            f"$ {' '.join(cmd)}\nreturncode: {proc.returncode}\n\n"
            f"--- STDOUT ---\n{proc.stdout}\n--- STDERR ---\n{proc.stderr}\n"
        )
        return VerifyResult(
            passed=(proc.returncode == 0),
            returncode=proc.returncode,
            duration_seconds=round(duration, 3),
            command=cmd,
        )
    except subprocess.TimeoutExpired:
        duration = time.time() - started
        log_path.write_text(f"$ {' '.join(cmd)}\nTIMEOUT after {timeout}s\n")
        return VerifyResult(
            passed=False,
            returncode=-1,
            duration_seconds=round(duration, 3),
            command=cmd,
            timed_out=True,
        )
