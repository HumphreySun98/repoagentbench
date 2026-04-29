import json
from pathlib import Path

import pytest

from repoagentbench.runs import (
    RunSummary,
    list_runs,
    render_diff,
    render_report,
    resolve_run_dir,
)


def _write_run(
    runs_dir: Path,
    run_id: str,
    *,
    task_id: str = "demo",
    agent: str = "mock-fix",
    status: str = "PASS",
    pre_passed: bool = False,
    post_passed: bool = True,
    duration: float = 5.0,
    files_changed: int = 1,
    base_commit: str | None = None,
) -> Path:
    """Write a minimal but schema-correct run-dir for tests to consume."""
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "schema_version": "1",
        "run_id": run_id,
        "task_id": task_id,
        "task_path": str(runs_dir.parent / "tasks" / task_id),
        "agent": agent,
        "base_commit": base_commit,
        "started_at": "2026-04-29T00:00:00Z",
        "harness_version": "0.1.0",
    }
    status_payload = {
        "schema_version": "1",
        "run_id": run_id,
        "task_id": task_id,
        "agent": agent,
        "status": status,
        "passed": status == "PASS",
        "failure_stage": None if status == "PASS" else "post_verify",
        "summary": "test fixture",
        "duration_seconds": duration,
        "pre_verify": {"passed": pre_passed, "returncode": 0 if pre_passed else 1, "duration_seconds": 1.0},
        "post_verify": {"passed": post_passed, "returncode": 0 if post_passed else 1, "duration_seconds": 1.0},
    }
    events = [
        {"ts": "2026-04-29T00:00:00.000Z", "type": "run.started"},
        {
            "ts": "2026-04-29T00:00:01.000Z",
            "type": "diff.captured",
            "files_changed": files_changed,
            "lines_added": 3,
            "lines_removed": 1,
        },
        {"ts": "2026-04-29T00:00:05.000Z", "type": "run.finished", "status": status},
    ]
    (run_dir / "manifest.json").write_text(json.dumps(manifest))
    (run_dir / "status.json").write_text(json.dumps(status_payload))
    (run_dir / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return run_dir


# ---- RunSummary.from_run_dir ----

def test_run_summary_reads_manifest_status_and_events(tmp_path):
    run_dir = _write_run(tmp_path, "20260429T000000Z__demo__mock-fix__abc123",
                          base_commit="deadbeef", files_changed=4)
    summary = RunSummary.from_run_dir(run_dir)
    assert summary.run_id == "20260429T000000Z__demo__mock-fix__abc123"
    assert summary.task_id == "demo"
    assert summary.agent == "mock-fix"
    assert summary.base_commit == "deadbeef"
    assert summary.status == "PASS"
    assert summary.pre_verify_passed is False
    assert summary.post_verify_passed is True
    assert summary.files_changed == 4
    assert summary.lines_added == 3


def test_run_summary_handles_missing_diff_event(tmp_path):
    """A run might crash before emitting diff.captured. files_changed is then None."""
    run_dir = tmp_path / "20260429T000000Z__demo__mock-fix__xxx"
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({
        "schema_version": "1", "run_id": run_dir.name, "task_id": "demo",
        "task_path": "/x", "agent": "mock-fix", "base_commit": None,
        "started_at": "...", "harness_version": "0.1.0",
    }))
    (run_dir / "status.json").write_text(json.dumps({
        "schema_version": "1", "run_id": run_dir.name, "task_id": "demo",
        "agent": "mock-fix", "status": "FAIL", "passed": False,
        "failure_stage": "post_verify", "summary": "", "duration_seconds": 1.0,
        "pre_verify": {"passed": False, "returncode": 1, "duration_seconds": 0.5},
        "post_verify": {"passed": False, "returncode": 1, "duration_seconds": 0.5},
    }))
    # No events.jsonl at all
    summary = RunSummary.from_run_dir(run_dir)
    assert summary.files_changed is None


# ---- list_runs ----

def test_list_runs_finds_valid_dirs(tmp_path):
    _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__a")
    _write_run(tmp_path, "20260429T000002Z__demo__aider__b", agent="aider", status="FAIL", post_passed=False)
    summaries = list_runs(tmp_path)
    assert len(summaries) == 2


def test_list_runs_skips_legacy_dirs(tmp_path):
    """Pre-v0.0.6 dirs (no manifest.json) must be silently ignored."""
    _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__valid")
    legacy = tmp_path / "1777440000-deadbe"
    legacy.mkdir()
    (legacy / "status.json").write_text("{}")  # has status but no manifest
    summaries = list_runs(tmp_path)
    assert len(summaries) == 1
    assert summaries[0].run_id.endswith("__valid")


def test_list_runs_returns_empty_for_missing_dir(tmp_path):
    assert list_runs(tmp_path / "does-not-exist") == []


# ---- resolve_run_dir ----

def test_resolve_run_dir_full_id(tmp_path):
    full = "20260429T000001Z__demo__mock-fix__abc123"
    expected = _write_run(tmp_path, full)
    assert resolve_run_dir(full, tmp_path) == expected


def test_resolve_run_dir_unique_prefix(tmp_path):
    expected = _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__unique1")
    _write_run(tmp_path, "20260429T999999Z__other__aider__zzzz", agent="aider")
    # The timestamp prefix uniquely identifies the first run
    assert resolve_run_dir("20260429T000001Z", tmp_path) == expected


def test_resolve_run_dir_ambiguous_prefix_raises(tmp_path):
    _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__a")
    _write_run(tmp_path, "20260429T000002Z__demo__mock-fix__b")
    with pytest.raises(RuntimeError, match="Ambiguous"):
        resolve_run_dir("20260429", tmp_path)


def test_resolve_run_dir_no_match_raises(tmp_path):
    _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__a")
    with pytest.raises(FileNotFoundError):
        resolve_run_dir("not-a-real-prefix", tmp_path)


# ---- render_report ----

def test_render_report_groups_by_task_and_aggregates_by_agent(tmp_path):
    _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__a", task_id="demo", agent="mock-fix")
    _write_run(tmp_path, "20260429T000002Z__demo__aider__b", task_id="demo", agent="aider",
               status="FAIL", post_passed=False)
    _write_run(tmp_path, "20260429T000003Z__click__mock-fix__c", task_id="click", agent="mock-fix")
    report = render_report(list_runs(tmp_path))
    # Per-task sections present
    assert "## `click`" in report
    assert "## `demo`" in report
    # Agent aggregate present and reflects the 2 mock-fix passes vs 1 aider fail
    assert "## Aggregate by agent" in report
    assert "| mock-fix | 2 | 2 | 100% |" in report
    assert "| aider | 1 | 0 | 0% |" in report


def test_render_report_filters_by_task(tmp_path):
    _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__a", task_id="demo")
    _write_run(tmp_path, "20260429T000002Z__click__mock-fix__b", task_id="click")
    report = render_report(list_runs(tmp_path), task_filter="demo")
    assert "## `demo`" in report
    assert "## `click`" not in report


def test_render_report_empty(tmp_path):
    assert "_No runs found._" in render_report([])


# ---- render_diff ----

def test_render_diff_marks_differing_fields(tmp_path):
    a_dir = _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__a", duration=4.0)
    b_dir = _write_run(tmp_path, "20260429T000002Z__demo__aider__b",
                       agent="aider", status="FAIL", post_passed=False, duration=300.0)
    a = RunSummary.from_run_dir(a_dir)
    b = RunSummary.from_run_dir(b_dir)
    diff = render_diff(a, b)
    # Same task → no warning banner
    assert "Different tasks" not in diff
    # Differing fields should have the ← marker
    lines_with_marker = [l for l in diff.splitlines() if "| ← |" in l]
    differing = " ".join(lines_with_marker)
    assert "Agent" in differing
    assert "Status" in differing
    assert "Duration" in differing
    # Same fields don't get the marker
    assert "Pre verify" not in differing  # both had pre_passed=False


def test_render_diff_warns_on_different_tasks(tmp_path):
    a_dir = _write_run(tmp_path, "20260429T000001Z__demo__mock-fix__a", task_id="demo")
    b_dir = _write_run(tmp_path, "20260429T000002Z__click__mock-fix__b", task_id="click")
    diff = render_diff(RunSummary.from_run_dir(a_dir), RunSummary.from_run_dir(b_dir))
    assert "Different tasks" in diff
