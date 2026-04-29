import json
import re

from repoagentbench.events import EventLog


def test_event_log_emits_one_jsonl_record_per_call(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.emit("run.started", run_id="x", agent="mock-fix")
        log.emit("run.finished", status="PASS", duration_seconds=1.0)
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(lines) == 2
    assert lines[0]["type"] == "run.started"
    assert lines[0]["run_id"] == "x"
    assert lines[1]["type"] == "run.finished"
    assert lines[1]["status"] == "PASS"


def test_event_log_includes_iso_timestamp(tmp_path):
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.emit("ping")
    record = json.loads(path.read_text().splitlines()[0])
    # ISO 8601 with millisecond precision and Z suffix
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", record["ts"])


def test_event_log_streams_so_partial_traces_are_readable(tmp_path):
    """A crash mid-run should still leave readable events for everything written so far."""
    path = tmp_path / "events.jsonl"
    log = EventLog(path)
    log.emit("a")
    log.emit("b")
    # Read without closing — the file should already contain both lines
    content = path.read_text()
    assert content.count("\n") == 2
    assert '"type": "a"' in content
    assert '"type": "b"' in content
    log.close()


def test_event_log_close_is_idempotent(tmp_path):
    log = EventLog(tmp_path / "events.jsonl")
    log.emit("ping")
    log.close()
    log.close()  # second close must not raise


def test_event_log_serializes_path_objects(tmp_path):
    """Several events emit Path values; the writer must not crash on them."""
    path = tmp_path / "events.jsonl"
    with EventLog(path) as log:
        log.emit("workdir.copied", path=tmp_path)
    record = json.loads(path.read_text().splitlines()[0])
    assert record["path"] == str(tmp_path)
