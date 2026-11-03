#!/usr/bin/env python3
"""Summarize per-request duration_ms values for one explicitly identified run."""
import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path


def summarize(path, run_id, timing_scope, identity):
    if not run_id.strip() or not timing_scope.strip() or not identity.strip():
        raise ValueError("run-id, timing-scope and identity must be non-empty")
    values = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "duration_ms" not in reader.fieldnames:
            raise ValueError("CSV must contain a duration_ms column")
        expected = {"run_id": run_id, "identity": identity, "timing_scope": timing_scope}
        for line, row in enumerate(reader, 2):
            for column, declared in expected.items():
                if column in reader.fieldnames and row.get(column) != declared:
                    raise ValueError("{} column disagrees with CLI declaration at CSV line {}".format(column, line))
            raw = row.get("duration_ms", "")
            try:
                value = float(raw)
            except (TypeError, ValueError):
                raise ValueError("invalid duration_ms at CSV line {}".format(line))
            if not math.isfinite(value) or value < 0:
                raise ValueError("duration_ms must be finite and nonnegative at CSV line {}".format(line))
            values.append(value)
    if not values:
        raise ValueError("CSV has no timing samples")
    ordered = sorted(values)
    # Nearest-rank percentile: x[ceil(p*n)-1], one-based rank.
    def nearest_rank(p):
        return ordered[math.ceil(p * len(ordered)) - 1]
    return {"schema_version": 1, "status": "ok",
            "interpretation": "Descriptive timings for the supplied samples; not a throughput guarantee or model-quality result.",
            "run_id": run_id, "identity": identity, "timing_scope": timing_scope,
            "sample_count": len(values), "duration_unit": "ms", "minimum": min(values),
            "median": statistics.median(values), "p50_nearest_rank": nearest_rank(0.50),
            "p95_nearest_rank": nearest_rank(0.95) if len(values) > 1 else None, "maximum": max(values),
            "percentile_method": "nearest rank, sorted[x[ceil(p*n)-1]] with one-based rank",
            "limitations": (["one sample: P95 is not reported; collect repeated requests for a distribution"]
                            if len(values) == 1 else [])}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv_file"); p.add_argument("--run-id", required=True)
    p.add_argument("--identity", required=True, help="model/package/board/build identity label")
    p.add_argument("--timing-scope", required=True, help="explicit start/end boundary, e.g. request end-to-end")
    args = p.parse_args(argv)
    try:
        result = summarize(args.csv_file, args.run_id, args.timing_scope, args.identity)
    except (OSError, ValueError, csv.Error) as exc:
        print(json.dumps({"schema_version": 1, "status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
