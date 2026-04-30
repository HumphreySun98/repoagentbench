"""Render docs/social-preview.png — the 1280x640 image GitHub shows when
the repo URL is unfurled on Twitter, Slack, HN comment previews, etc.

Upload via repo Settings → Options → Social preview.

Re-run after changing the leaderboard:
    python scripts/make_social_preview.py
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from repoagentbench.runs import list_runs  # noqa: E402

PASS_COLOR = "#2ea043"
FAIL_COLOR = "#cf222e"
NA_COLOR = "#6e7781"
BG_COLOR = "#0d1117"
FG_COLOR = "#f0f6fc"
ACCENT = "#58a6ff"


def main() -> None:
    runs = list_runs(REPO_ROOT / ".runs")

    matrix: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in runs:
        matrix[(r.agent, r.model or "")][r.task_id].append(r.status)
    real_tasks = sorted({r.task_id for r in runs if r.task_id != "demo"})

    def passes(combo):
        return sum(1 for t in real_tasks
                   if matrix[combo].get(t) and "PASS" in matrix[combo][t])
    rows = sorted(matrix.keys(), key=lambda c: (-passes(c), c[0], c[1]))

    fig = plt.figure(figsize=(12.8, 6.4), facecolor=BG_COLOR, dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 12.8)
    ax.set_ylim(0, 6.4)
    ax.invert_yaxis()
    ax.axis("off")
    ax.set_facecolor(BG_COLOR)

    # Title block
    ax.text(0.5, 0.7, "RepoAgentBench",
            fontsize=42, fontweight="bold", color=FG_COLOR, ha="left", va="top")
    ax.text(0.5, 1.5, "SWE-bench for your codebase.",
            fontsize=22, color=ACCENT, ha="left", va="top", style="italic")

    # Big finding banner
    ax.text(0.5, 2.45,
            "0/4 frontier models passed all 3 real PRs.",
            fontsize=20, fontweight="bold", color=FG_COLOR, ha="left", va="top")
    ax.text(0.5, 2.95,
            "Same model + different agent harness = different outcome.",
            fontsize=14, color="#9da7b3", ha="left", va="top")

    # Mini heatmap on the right
    grid_left, grid_top = 7.2, 0.9
    cell_w, cell_h = 1.0, 0.55
    for c_idx, t in enumerate(real_tasks):
        ax.text(grid_left + cell_w * (c_idx + 0.5), grid_top - 0.15,
                t.replace("click-pr-", "#"),
                fontsize=11, color=FG_COLOR, ha="center", va="bottom", fontweight="bold")
    ax.text(grid_left + cell_w * (len(real_tasks) + 0.5), grid_top - 0.15,
            "rate", fontsize=11, color=FG_COLOR, ha="center", va="bottom", fontweight="bold")

    for r_idx, combo in enumerate(rows[:6]):  # cap rows for the small space
        agent, model = combo
        # short label
        if model:
            short = model.split("/")[-1].replace("claude-", "").replace("-preview", "")
            short = short.replace("-20250929", "").replace("-20251001", "")
        else:
            short = agent
        ax.text(grid_left - 0.15, grid_top + cell_h * (r_idx + 0.5), short,
                fontsize=10, color=FG_COLOR, ha="right", va="center", family="monospace")
        for c_idx, t in enumerate(real_tasks):
            statuses = matrix[combo].get(t, [])
            if not statuses:
                color, txt = NA_COLOR, "—"
            elif "PASS" in statuses:
                color, txt = PASS_COLOR, "✓"
            else:
                color, txt = FAIL_COLOR, "✗"
            ax.add_patch(Rectangle(
                (grid_left + cell_w * c_idx + 0.05,
                 grid_top + cell_h * r_idx + 0.05),
                cell_w - 0.1, cell_h - 0.1,
                facecolor=color, edgecolor=BG_COLOR, linewidth=2))
            ax.text(grid_left + cell_w * (c_idx + 0.5),
                    grid_top + cell_h * (r_idx + 0.5),
                    txt, fontsize=14, color="white", ha="center", va="center",
                    fontweight="bold")
        n_attempts = sum(1 for t in real_tasks if matrix[combo].get(t))
        n_passes = passes(combo)
        if n_attempts:
            rate = f"{n_passes}/{n_attempts}"
            color = PASS_COLOR if n_passes == n_attempts else (
                FAIL_COLOR if n_passes == 0 else "#bf8700")
        else:
            rate, color = "—", NA_COLOR
        ax.add_patch(Rectangle(
            (grid_left + cell_w * len(real_tasks) + 0.05,
             grid_top + cell_h * r_idx + 0.05),
            cell_w - 0.1, cell_h - 0.1,
            facecolor=color, edgecolor=BG_COLOR, linewidth=2))
        ax.text(grid_left + cell_w * (len(real_tasks) + 0.5),
                grid_top + cell_h * (r_idx + 0.5),
                rate, fontsize=11, color="white", ha="center", va="center",
                fontweight="bold")

    # Bottom panel: bullet points
    bullets = [
        ("•", "Mine merged PRs into reproducible benchmark tasks"),
        ("•", "Per-task venv isolation, structured run artifacts"),
        ("•", "Adapters: claude-code, aider (Opus 4.7 / GPT-5.5 / Sonnet 4.6 / Gemini 3.1 Pro)"),
        ("•", "Local-first. Contamination-free if you mine fresh PRs."),
    ]
    for i, (b, line) in enumerate(bullets):
        ax.text(0.5, 4.0 + 0.45 * i, f"{b}  {line}",
                fontsize=14, color=FG_COLOR, ha="left", va="top", family="sans-serif")

    # Footer URL
    ax.text(0.5, 6.1, "github.com/HumphreySun98/repoagentbench",
            fontsize=13, color=ACCENT, ha="left", va="bottom", family="monospace")
    ax.text(12.3, 6.1, "pip install repoagentbench",
            fontsize=13, color="#9da7b3", ha="right", va="bottom", family="monospace")

    out = REPO_ROOT / "docs" / "social-preview.png"
    plt.savefig(out, dpi=100, facecolor=BG_COLOR)
    print(f"Wrote {out.relative_to(REPO_ROOT)} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
