import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .base import Agent


# When Claude Code is installed via the VSCode extension (most users), the
# binary lives inside the extension's resources dir and is not on PATH for
# subprocesses. Probe a few known locations, but RAB_CLAUDE_BIN wins.
_CLAUDE_PROBE_PATHS = [
    Path.home() / ".vscode-server/extensions",
    Path.home() / ".vscode/extensions",
    Path.home() / ".cursor-server/extensions",
    Path.home() / ".cursor/extensions",
]


class ClaudeCodeAgent(Agent):
    name = "claude-code"

    def run(self, workdir: Path, goal: str, task_path: Path, log_path: Path) -> dict:
        claude_bin = _find_claude()
        if claude_bin is None:
            log_path.write_text(
                "`claude` CLI not found.\n"
                "Tried: $RAB_CLAUDE_BIN, PATH, and the VSCode/Cursor extension dirs.\n"
                "Install Claude Code (https://docs.claude.com/en/docs/claude-code) "
                "or set RAB_CLAUDE_BIN.\n"
            )
            return {"agent": self.name, "error": "claude_cli_not_installed"}

        cmd = [
            claude_bin, "-p", goal,
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


def _find_claude() -> Optional[str]:
    explicit = os.environ.get("RAB_CLAUDE_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    # Fall back to searching VSCode/Cursor extension dirs for the bundled binary.
    for ext_dir in _CLAUDE_PROBE_PATHS:
        if not ext_dir.exists():
            continue
        # Prefer the highest-versioned anthropic.claude-code-* extension.
        candidates = sorted(ext_dir.glob("anthropic.claude-code-*"), reverse=True)
        for cand in candidates:
            for rel in ("resources/native-binary/claude", "bin/claude"):
                bin_path = cand / rel
                if bin_path.exists() and os.access(bin_path, os.X_OK):
                    return str(bin_path)
    return None
