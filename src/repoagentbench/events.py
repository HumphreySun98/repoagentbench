"""Streaming events.jsonl writer for one run.

Each run-dir contains an events.jsonl that records lifecycle events as they
happen (run.started, verify.started/finished per phase, agent.started/finished,
diff.captured, run.finished). The file is line-buffered and flushed after each
emit so a crash mid-run still leaves a usable partial trace.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class EventLog:
    """Append-only writer for a run's events.jsonl."""

    def __init__(self, path: Path):
        self._path = path
        self._fp: IO[str] = path.open("a", buffering=1, encoding="utf-8")

    def emit(self, event_type: str, **fields: Any) -> None:
        record = {"ts": _now_iso(), "type": event_type}
        record.update(fields)
        self._fp.write(json.dumps(record, default=str) + "\n")
        self._fp.flush()

    def close(self) -> None:
        if not self._fp.closed:
            self._fp.close()

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
