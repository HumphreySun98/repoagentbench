import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerifyResult:
    passed: bool
    returncode: int


def run_verify(workdir: Path, log_path: Path, timeout: int = 300) -> VerifyResult:
    """Run task verification.

    Convention: if the task contains `verify.sh`, run it. Otherwise default to `pytest`
    (falling back to `python -m pytest` when the `pytest` binary is not on PATH).
    """
    verify_script = workdir / "verify.sh"
    if verify_script.exists():
        cmd = ["bash", str(verify_script)]
    elif shutil.which("pytest"):
        cmd = ["pytest", "-x", "--tb=short"]
    else:
        cmd = [sys.executable, "-m", "pytest", "-x", "--tb=short"]

    try:
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        log_path.write_text(
            f"$ {' '.join(cmd)}\nreturncode: {proc.returncode}\n\n"
            f"--- STDOUT ---\n{proc.stdout}\n--- STDERR ---\n{proc.stderr}\n"
        )
        return VerifyResult(passed=(proc.returncode == 0), returncode=proc.returncode)
    except subprocess.TimeoutExpired:
        log_path.write_text(f"$ {' '.join(cmd)}\nTIMEOUT after {timeout}s\n")
        return VerifyResult(passed=False, returncode=-1)
