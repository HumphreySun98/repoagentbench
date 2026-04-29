"""Read and aggregate structured run-dirs produced by the runner.

A run-dir contains manifest.json, status.json, verification.json, and
events.jsonl. This module exposes a typed view (`RunSummary`) plus
discovery, lookup, and rendering helpers used by the `report`, `replay`,
and `diff` subcommands.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RunSummary:
    run_id: str
    run_dir: Path
    task_id: str
    task_path: Path
    agent: str
    base_commit: Optional[str]
    started_at: Optional[str]
    status: str
    failure_stage: Optional[str]
    summary: str
    duration_seconds: float
    pre_verify_passed: bool
    pre_verify_duration: float
    post_verify_passed: bool
    post_verify_duration: float
    files_changed: Optional[int]
    lines_added: Optional[int]
    lines_removed: Optional[int]

    @classmethod
    def from_run_dir(cls, run_dir: Path) -> "RunSummary":
        manifest = json.loads((run_dir / "manifest.json").read_text())
        status = json.loads((run_dir / "status.json").read_text())
        diff_stats = _scan_diff_event(run_dir / "events.jsonl")
        pre = status.get("pre_verify", {})
        post = status.get("post_verify", {})
        return cls(
            run_id=manifest["run_id"],
            run_dir=run_dir,
            task_id=manifest["task_id"],
            task_path=Path(manifest["task_path"]),
            agent=manifest["agent"],
            base_commit=manifest.get("base_commit"),
            started_at=manifest.get("started_at"),
            status=status["status"],
            failure_stage=status.get("failure_stage"),
            summary=status.get("summary", ""),
            duration_seconds=status["duration_seconds"],
            pre_verify_passed=pre.get("passed", False),
            pre_verify_duration=pre.get("duration_seconds", 0.0),
            post_verify_passed=post.get("passed", False),
            post_verify_duration=post.get("duration_seconds", 0.0),
            files_changed=diff_stats.get("files_changed"),
            lines_added=diff_stats.get("lines_added"),
            lines_removed=diff_stats.get("lines_removed"),
        )


def _scan_diff_event(events_path: Path) -> dict:
    if not events_path.exists():
        return {}
    for raw in events_path.read_text().splitlines():
        if not raw.strip():
            continue
        try:
            evt = json.loads(raw)
        except ValueError:
            continue
        if evt.get("type") == "diff.captured":
            return {k: evt[k] for k in ("files_changed", "lines_added", "lines_removed") if k in evt}
    return {}


def list_runs(runs_dir: Path) -> list[RunSummary]:
    """Discover run-dirs in runs_dir. Skips dirs without manifest.json
    (e.g. legacy <unix_ts>-<uuid6> runs from before v0.0.6)."""
    if not runs_dir.exists():
        return []
    summaries: list[RunSummary] = []
    for entry in sorted(runs_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "manifest.json").exists() or not (entry / "status.json").exists():
            continue
        try:
            summaries.append(RunSummary.from_run_dir(entry))
        except (ValueError, KeyError, OSError):
            continue
    return summaries


def resolve_run_dir(run_id: str, runs_dir: Path) -> Path:
    """Resolve a `--run <id>` argument to a run-dir path. Accepts the full
    run_id, a unique prefix, or an absolute path to the run-dir itself."""
    candidate = Path(run_id)
    if candidate.is_absolute() and candidate.exists():
        return candidate
    direct = runs_dir / run_id
    if direct.exists():
        return direct
    matches = [p for p in runs_dir.iterdir() if p.is_dir() and p.name.startswith(run_id)]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise FileNotFoundError(f"No run matching {run_id!r} under {runs_dir}")
    raise RuntimeError(
        f"Ambiguous run id {run_id!r}; matches: " + ", ".join(p.name for p in matches)
    )


def render_report(summaries: list[RunSummary], task_filter: Optional[str] = None) -> str:
    if task_filter:
        summaries = [s for s in summaries if s.task_id == task_filter]
    if not summaries:
        return "_No runs found._\n"

    by_task: dict[str, list[RunSummary]] = {}
    for s in summaries:
        by_task.setdefault(s.task_id, []).append(s)

    lines: list[str] = ["# RepoAgentBench Report", ""]
    lines.append(f"_{len(summaries)} run(s) across {len(by_task)} task(s)._")
    lines.append("")

    for task_id, runs in sorted(by_task.items()):
        lines.append(f"## `{task_id}`")
        lines.append("")
        if runs[0].base_commit:
            lines.append(f"Base commit: `{runs[0].base_commit[:12]}`")
            lines.append("")
        lines.append("| Run | Agent | Status | Pre | Post | Files | Duration |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in sorted(runs, key=lambda x: x.run_id):
            pre = "FAIL" if not r.pre_verify_passed else "PASS"
            post = "PASS" if r.post_verify_passed else "FAIL"
            files = str(r.files_changed) if r.files_changed is not None else "—"
            short = r.run_id.split("__")[0]
            lines.append(
                f"| `{short}` | {r.agent} | **{r.status}** | {pre} | {post} | {files} | {r.duration_seconds:.1f}s |"
            )
        lines.append("")

    by_agent: dict[str, list[RunSummary]] = {}
    for s in summaries:
        by_agent.setdefault(s.agent, []).append(s)
    if len(by_agent) > 1 or len(summaries) > 1:
        lines.append("## Aggregate by agent")
        lines.append("")
        lines.append("| Agent | Runs | Passed | Pass rate | Avg duration |")
        lines.append("|---|---|---|---|---|")
        for agent, runs in sorted(by_agent.items()):
            passed = sum(1 for r in runs if r.status == "PASS")
            total = len(runs)
            rate = (passed / total * 100) if total else 0.0
            avg_dur = sum(r.duration_seconds for r in runs) / total if total else 0.0
            lines.append(f"| {agent} | {total} | {passed} | {rate:.0f}% | {avg_dur:.1f}s |")
        lines.append("")

    return "\n".join(lines)


def render_diff(a: RunSummary, b: RunSummary) -> str:
    lines: list[str] = ["# Run diff", ""]
    if a.task_id != b.task_id:
        lines.append(f"> ⚠️ Different tasks: `{a.task_id}` vs `{b.task_id}`")
        lines.append("")
    rows: list[tuple[str, str, str]] = [
        ("Run", a.run_id, b.run_id),
        ("Task", a.task_id, b.task_id),
        ("Agent", a.agent, b.agent),
        ("Status", a.status, b.status),
        ("Failure stage", a.failure_stage or "—", b.failure_stage or "—"),
        ("Duration (s)", f"{a.duration_seconds:.2f}", f"{b.duration_seconds:.2f}"),
        ("Pre verify", "PASS" if a.pre_verify_passed else "FAIL",
                       "PASS" if b.pre_verify_passed else "FAIL"),
        ("Post verify", "PASS" if a.post_verify_passed else "FAIL",
                        "PASS" if b.post_verify_passed else "FAIL"),
        ("Files changed",
         "—" if a.files_changed is None else str(a.files_changed),
         "—" if b.files_changed is None else str(b.files_changed)),
        ("Lines added",
         "—" if a.lines_added is None else str(a.lines_added),
         "—" if b.lines_added is None else str(b.lines_added)),
        ("Lines removed",
         "—" if a.lines_removed is None else str(a.lines_removed),
         "—" if b.lines_removed is None else str(b.lines_removed)),
    ]
    lines.append("| Field | A | B | |")
    lines.append("|---|---|---|---|")
    for label, av, bv in rows:
        marker = "" if av == bv else "←"
        lines.append(f"| {label} | `{av}` | `{bv}` | {marker} |")
    lines.append("")
    return "\n".join(lines)
