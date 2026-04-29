import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .base import Agent


# Discovery order: explicit env var, the conda env we recommend in the README,
# whatever's on PATH. Aider's deps (litellm, etc.) tend to conflict with random
# project deps, so a dedicated env is cleaner than a system-wide install.
DEFAULT_CONDA_BIN = Path.home() / "miniforge/envs/aider-rab/bin/aider"
FALLBACK_CONDA_BINS = [
    Path.home() / "miniconda3/envs/aider-rab/bin/aider",
    Path.home() / "anaconda3/envs/aider-rab/bin/aider",
]
DEFAULT_MODEL = "anthropic/claude-sonnet-4-6"


class AiderAgent(Agent):
    name = "aider"

    def run(self, workdir: Path, goal: str, task_path: Path, log_path: Path) -> dict:
        aider_bin = _find_aider()
        if aider_bin is None:
            log_path.write_text(
                "aider binary not found.\n"
                "Install:  conda create -n aider-rab python=3.11 -y\n"
                "          conda run -n aider-rab pip install aider-chat\n"
                "Or set RAB_AIDER_BIN to an aider executable.\n"
            )
            return {"agent": self.name, "error": "aider_not_installed"}

        model = os.environ.get("RAB_AIDER_MODEL", DEFAULT_MODEL)
        required_key = _required_env_key(model)
        if required_key and required_key not in os.environ:
            log_path.write_text(
                f"{required_key} is not set; aider needs it to call {model}.\n"
            )
            return {"agent": self.name, "model": model, "error": f"no_{required_key.lower()}"}
        cmd = [
            aider_bin,
            "--message", goal,
            "--yes-always",
            "--no-auto-commits",
            "--no-pretty",
            "--no-stream",
            "--no-show-model-warnings",
            "--no-check-update",
            "--no-detect-urls",  # goal.md often contains the source PR URL;
            # without this flag aider tries to scrape it, which adds 30s+ of
            # latency, may trigger Playwright install prompts, and exfiltrates
            # the run via an outbound HTTP request we did not ask for.
        ]
        # Pass per-model overrides so frontier reasoning models (Opus 4.7,
        # GPT-5.x, Gemini 3.x) don't choke on aider's default temperature=0.
        settings_file = Path.cwd() / "aider-model-settings.yml"
        if settings_file.exists():
            cmd.extend(["--model-settings-file", str(settings_file)])
        # If the task workdir is not its own git repo, pass --no-git so aider
        # doesn't walk up the directory tree to a parent .git (which then makes
        # it use absolute paths it refuses to add to the chat). PR-mined tasks
        # have their own .git and should keep it for repo-map context.
        if not (workdir / ".git").exists():
            cmd.append("--no-git")
        cmd.extend(["--model", model])
        try:
            proc = subprocess.run(
                cmd,
                cwd=workdir,
                capture_output=True,
                text=True,
                timeout=1200,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            log_path.write_text(
                f"$ {aider_bin} --message ... --model {model}\n"
                f"TIMEOUT after 1200s\n"
            )
            return {"agent": self.name, "model": model, "error": "timeout"}

        log_path.write_text(
            f"$ {aider_bin} --message <goal> --model {model} "
            f"--yes-always --no-auto-commits --no-pretty --no-stream\n"
            f"returncode: {proc.returncode}\n\n"
            f"--- STDOUT ---\n{proc.stdout}\n"
            f"--- STDERR ---\n{proc.stderr}\n"
        )
        return {
            "agent": self.name,
            "model": model,
            "returncode": proc.returncode,
        }


def _required_env_key(model: str) -> str:
    """Return the env var aider/litellm needs for the given model. Empty if
    we don't have a confident mapping (let aider raise its own error)."""
    m = model.lower()
    if m.startswith("anthropic/") or m.startswith("claude"):
        return "ANTHROPIC_API_KEY"
    if m.startswith("openai/") or m.startswith("gpt"):
        return "OPENAI_API_KEY"
    if m.startswith("gemini/") or m.startswith("gemini-") or m.startswith("vertex_ai"):
        return "GEMINI_API_KEY"
    return ""


def _find_aider() -> Optional[str]:
    explicit = os.environ.get("RAB_AIDER_BIN")
    if explicit and Path(explicit).exists():
        return explicit
    for candidate in [DEFAULT_CONDA_BIN, *FALLBACK_CONDA_BINS]:
        if candidate.exists():
            return str(candidate)
    return shutil.which("aider")
