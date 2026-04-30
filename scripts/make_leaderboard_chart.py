"""Render docs/leaderboard.png from .runs/ using matplotlib.

Re-run after adding new tasks or models:
    python scripts/make_leaderboard_chart.py

Output is a heatmap with one row per (agent, model), one column per task,
plus a "Pass rate" column. PASS/FAIL/N-A cells are color-coded.
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")  # headless: don't try to open a display

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from repoagentbench.runs import list_runs  # noqa: E402


# Colors tuned for both light + dark GitHub themes
PASS_COLOR = "#2ea043"
FAIL_COLOR = "#cf222e"
NA_COLOR = "#6e7781"
HEADER_COLOR = "#1f2328"
GRID_COLOR = "#d0d7de"


def main() -> None:
    runs = list_runs(REPO_ROOT / ".runs")
    if not runs:
        sys.exit("No runs in .runs/ — generate some first with `repoagentbench run-one`.")

    # Index: (agent, model) -> task -> [statuses]  (could be multiple runs)
    matrix: dict[tuple[str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for r in runs:
        matrix[(r.agent, r.model or "")][r.task_id].append(r.status)

    # Filter out the demo task — leaderboard is about real PRs
    real_tasks = sorted({r.task_id for r in runs if r.task_id != "demo"})

    # Sort rows so the most-passing combos sit on top
    def passes_on_real_tasks(combo: tuple[str, str]) -> int:
        return sum(
            1 for t in real_tasks
            if matrix[combo].get(t) and "PASS" in matrix[combo][t]
        )
    rows = sorted(matrix.keys(), key=lambda c: (-passes_on_real_tasks(c), c[0], c[1]))

    n_rows, n_cols = len(rows), len(real_tasks) + 1  # +1 for pass-rate column

    fig, ax = plt.subplots(figsize=(2.0 + 1.5 * n_cols, 1.0 + 0.55 * n_rows))
    ax.set_xlim(0, n_cols)
    ax.set_ylim(0, n_rows)
    ax.invert_yaxis()
    ax.axis("off")

    # Title
    ax.text(n_cols / 2, -0.7,
            f"RepoAgentBench: pass / fail across {len(real_tasks)} real PRs",
            ha="center", va="bottom", fontsize=13, fontweight="bold", color=HEADER_COLOR)

    # Column headers (PR numbers + Pass rate)
    for i, t in enumerate(real_tasks):
        ax.text(i + 0.5, -0.15, t.replace("click-pr-", "click #"),
                ha="center", va="bottom", fontsize=10, color=HEADER_COLOR, fontweight="bold")
    ax.text(len(real_tasks) + 0.5, -0.15, "Pass rate",
            ha="center", va="bottom", fontsize=10, color=HEADER_COLOR, fontweight="bold")

    # Cells
    for r_idx, combo in enumerate(rows):
        agent, model = combo
        # Row label (left of grid)
        label = f"{agent} + {model}" if model else agent
        ax.text(-0.05, r_idx + 0.5, label, ha="right", va="center",
                fontsize=10, color=HEADER_COLOR, family="monospace")

        # PR cells
        for c_idx, task in enumerate(real_tasks):
            statuses = matrix[combo].get(task, [])
            if not statuses:
                color, label_text = NA_COLOR, "—"
            elif "PASS" in statuses:
                color, label_text = PASS_COLOR, "PASS"
            else:
                color, label_text = FAIL_COLOR, "FAIL"
            ax.add_patch(Rectangle((c_idx + 0.05, r_idx + 0.1), 0.9, 0.8,
                                    facecolor=color, edgecolor=GRID_COLOR, linewidth=1))
            ax.text(c_idx + 0.5, r_idx + 0.5, label_text,
                    ha="center", va="center", fontsize=9.5, color="white", fontweight="bold")

        # Pass-rate cell
        n_attempts = sum(1 for t in real_tasks if matrix[combo].get(t))
        n_passes = passes_on_real_tasks(combo)
        if n_attempts == 0:
            rate_text, rate_color = "—", NA_COLOR
        else:
            pct = n_passes / n_attempts * 100
            rate_text = f"{n_passes}/{n_attempts}  ({pct:.0f}%)"
            rate_color = PASS_COLOR if pct == 100 else (FAIL_COLOR if pct == 0 else "#bf8700")
        ax.add_patch(Rectangle((len(real_tasks) + 0.05, r_idx + 0.1), 0.9, 0.8,
                                facecolor=rate_color, edgecolor=GRID_COLOR, linewidth=1))
        ax.text(len(real_tasks) + 0.5, r_idx + 0.5, rate_text,
                ha="center", va="center", fontsize=9.5, color="white", fontweight="bold")

    # Footer
    ax.text(n_cols / 2, n_rows + 0.55,
            "No frontier model passed all three PRs. Each fails on a different bug.",
            ha="center", va="top", fontsize=9.5, style="italic", color=HEADER_COLOR)

    plt.subplots_adjust(left=0.32, right=0.98, top=0.92, bottom=0.05)
    out = REPO_ROOT / "docs" / "leaderboard.png"
    out.parent.mkdir(exist_ok=True)
    plt.savefig(out, dpi=180, bbox_inches="tight", facecolor="white")
    print(f"Wrote {out.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
