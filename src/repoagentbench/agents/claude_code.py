import json
import shutil
import subprocess
from pathlib import Path

from .base import Agent


class ClaudeCodeAgent(Agent):
    name = "claude-code"

    def run(self, workdir: Path, goal: str, task_path: Path, log_path: Path) -> dict:
        if shutil.which("claude") is None:
            log_path.write_text("`claude` CLI not found on PATH. Install Claude Code first.\n")
            return {"agent": self.name, "error": "claude_cli_not_installed"}

        cmd = [
            "claude", "-p", goal,
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",
        ]
        proc = subprocess.run(
            cmd,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        log_path.write_text(
            f"$ {' '.join(cmd[:4])} ...\nreturncode: {proc.returncode}\n\n"
            f"--- STDOUT ---\n{proc.stdout}\n--- STDERR ---\n{proc.stderr}\n"
        )

        try:
            output = json.loads(proc.stdout)
        except json.JSONDecodeError:
            output = {"raw_stdout_preview": proc.stdout[:500]}

        return {
            "agent": self.name,
            "returncode": proc.returncode,
            "output": output,
        }
