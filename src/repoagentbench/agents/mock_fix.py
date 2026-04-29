import subprocess
from pathlib import Path

from .base import Agent


class MockFixAgent(Agent):
    """Applies a known solution.patch from the task. Used for smoke-testing the harness without burning API credits."""

    name = "mock-fix"

    def run(self, workdir: Path, goal: str, task_path: Path, log_path: Path) -> dict:
        solution = task_path / "solution.patch"
        if not solution.exists():
            log_path.write_text("No solution.patch in task; mock-fix did nothing.\n")
            return {"agent": self.name, "applied": False, "reason": "no_solution_patch"}

        proc = subprocess.run(
            ["patch", "-p1", "-i", str(solution)],
            cwd=workdir,
            capture_output=True,
            text=True,
        )
        log_path.write_text(
            f"$ patch -p1 -i {solution}\nreturncode: {proc.returncode}\n\n"
            f"--- STDOUT ---\n{proc.stdout}\n--- STDERR ---\n{proc.stderr}\n"
        )
        return {
            "agent": self.name,
            "applied": proc.returncode == 0,
            "returncode": proc.returncode,
        }
