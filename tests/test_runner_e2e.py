"""End-to-end smoke test: run mock-fix on examples/demo and assert the
artifact bundle is well-formed. Slow (~5s with venv bootstrap) but high
value — it catches integration regressions across runner / verify /
events / agents that pure unit tests miss.
"""

import json
import shutil
from pathlib import Path

import pytest

from repoagentbench.runner import run_one_task


REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_TASK = REPO_ROOT / "examples" / "demo"


@pytest.fixture
def out_dir(tmp_path):
    return tmp_path / ".runs"


def test_mock_fix_on_demo_produces_pass_with_full_artifact_bundle(out_dir):
    if not DEMO_TASK.exists():
        pytest.skip("examples/demo missing — repo is not in expected layout")

    result = run_one_task(DEMO_TASK, "mock-fix", out_dir)

    assert result.status == "PASS"
    assert result.pre_verify_passed is False  # task must establish a broken baseline
    assert result.post_verify_passed is True

    run_dir = result.run_dir
    # Required artifacts
    for fname in (
        "manifest.json", "status.json", "verification.json", "events.jsonl",
        "pre_verify.log", "post_verify.log", "agent.log", "diff.patch",
        "venv_bootstrap.log",
    ):
        assert (run_dir / fname).exists(), f"missing {fname}"
    assert (run_dir / "workdir").is_dir()

    # Run id matches the v0.0.6 schema
    assert "__demo__mock-fix__" in result.run_id
    assert result.run_id.startswith(("19", "20"))  # ISO timestamp prefix

    # Manifest content
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["schema_version"] == "1"
    assert manifest["task_id"] == "demo"
    assert manifest["agent"] == "mock-fix"

    # Status content
    status = json.loads((run_dir / "status.json").read_text())
    assert status["status"] == "PASS"
    assert status["passed"] is True
    assert status["failure_stage"] is None
    assert status["pre_verify"]["passed"] is False
    assert status["post_verify"]["passed"] is True

    # Verification content
    verification = json.loads((run_dir / "verification.json").read_text())
    phases = {p["phase"]: p for p in verification["phases"]}
    assert set(phases) == {"pre", "post"}
    assert phases["pre"]["passed"] is False
    assert phases["post"]["passed"] is True
    assert phases["pre"]["duration_seconds"] >= 0
    assert isinstance(phases["pre"]["command"], list)

    # Events lifecycle
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines() if line.strip()]
    types = [e["type"] for e in events]
    assert types[0] == "run.started"
    assert types[-1] == "run.finished"
    assert "verify.started" in types
    assert "verify.finished" in types
    assert "agent.started" in types
    assert "agent.finished" in types
    assert "diff.captured" in types
    # diff.captured includes file count
    diff_event = next(e for e in events if e["type"] == "diff.captured")
    assert diff_event["files_changed"] >= 1


def test_run_dir_isolation_preserves_original_task(out_dir):
    """The runner must not mutate the original task folder."""
    if not DEMO_TASK.exists():
        pytest.skip("examples/demo missing")
    before = sorted(p.name for p in DEMO_TASK.rglob("*") if p.is_file())
    run_one_task(DEMO_TASK, "mock-fix", out_dir)
    after = sorted(p.name for p in DEMO_TASK.rglob("*") if p.is_file())
    assert before == after, "original task tree was modified by the run"
