#!/usr/bin/env python3
"""Build per-run timelines from explicitly supplied DMA event records."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import OrderedDict
from pathlib import Path

sys.dont_write_bytecode = True


def parse_timestamp(value: str) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("event timestamp must be a string")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("event timestamp must include a UTC offset")
    return parsed


def audit(path: Path) -> tuple[dict, int]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or type(doc.get("schema_version")) is not int or doc.get("schema_version") != 1 or not isinstance(doc.get("events"), list):
        raise ValueError("expected object with schema_version=1 and events array")
    if not doc["events"]:
        raise ValueError("events must contain at least one event")
    runs = OrderedDict()
    sequence = []
    for i, event in enumerate(doc["events"]):
        if not isinstance(event, dict):
            raise ValueError(f"events[{i}] must be an object")
        run_id, name = event.get("run_id"), event.get("event")
        if not isinstance(run_id, str) or not run_id.strip() or not isinstance(name, str) or not name.strip():
            raise ValueError(f"events[{i}] requires non-empty string run_id and event")
        timestamp = parse_timestamp(event.get("timestamp"))
        row = dict(event)
        row["input_index"] = i
        row["parsed_timestamp"] = timestamp
        runs.setdefault(run_id, []).append(row)
        sequence.append(run_id)
    multiple_runs = len(runs) > 1
    run_segments = [run_id for i, run_id in enumerate(sequence) if i == 0 or run_id != sequence[i - 1]]
    interleaved = len(run_segments) != len(set(run_segments)) if multiple_runs else False
    anomalies = []
    rendered_runs = []
    for run_id, events in runs.items():
        previous = None
        output_events = []
        for event in events:
            stamp = event.pop("parsed_timestamp")
            if previous is not None and stamp < previous:
                anomalies.append({"run_id": run_id, "input_index": event["input_index"], "kind": "timestamp_reversal"})
            previous = stamp
            event["timestamp"] = stamp.isoformat()
            output_events.append(event)
        rendered_runs.append({"run_id": run_id, "events": output_events})
    clean = not multiple_runs and not anomalies
    result = {"schema_version": 1, "status": "single_run_chronological" if clean else "review_required",
              "run_count": len(runs), "multiple_runs": multiple_runs, "interleaved_runs": interleaved,
              "order_anomalies": anomalies, "runs": rendered_runs,
              "interpretation": "Input rows are grouped by run and kept in recorded order; timestamps expose reversals. No register semantics or root cause is inferred."}
    return result, (0 if clean else 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    args = parser.parse_args()
    try:
        result, code = audit(args.events)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
