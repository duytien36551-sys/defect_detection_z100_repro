#!/usr/bin/env python3
"""Read-only byte comparison. Contract, dtype and layout must be checked separately."""
import argparse
import hashlib
import json
import sys
from pathlib import Path

CHUNK_BYTES = 1024 * 1024


def compare(reference, observed, label):
    digests = [hashlib.sha256(), hashlib.sha256()]
    lengths = [0, 0]
    shared_differences = 0
    extra_bytes = 0
    first = None
    offset = 0
    with Path(reference).open("rb") as left, Path(observed).open("rb") as right:
        while True:
            a, b = left.read(CHUNK_BYTES), right.read(CHUNK_BYTES)
            if not a and not b:
                break
            digests[0].update(a)
            digests[1].update(b)
            lengths[0] += len(a)
            lengths[1] += len(b)
            common = min(len(a), len(b))
            if a != b:
                shared_differences += sum(x != y for x, y in zip(a, b))
                extra_bytes += abs(len(a) - len(b))
                if first is None:
                    index = next((i for i in range(common) if a[i] != b[i]), common)
                    first = {
                        "byte_offset": offset + index,
                        "reference_byte": a[index] if index < len(a) else None,
                        "observed_byte": b[index] if index < len(b) else None,
                    }
            offset += max(len(a), len(b))
    return {
        "schema_version": 1,
        "label": label,
        "status": "equal" if first is None else "different",
        "reference": {"path": str(reference), "bytes": lengths[0], "sha256": digests[0].hexdigest()},
        "observed": {"path": str(observed), "bytes": lengths[1], "sha256": digests[1].hexdigest()},
        "shared_different_bytes": shared_differences,
        "extra_bytes": extra_bytes,
        "different_positions": shared_differences + extra_bytes,
        "first_difference": first,
        "interpretation": "Byte equality only; verify input, model, dtype, shape and layout independently.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference")
    parser.add_argument("observed")
    parser.add_argument("--label", default="binary-comparison")
    args = parser.parse_args()
    try:
        result = compare(args.reference, args.observed, args.label)
    except OSError as exc:
        print(json.dumps({"schema_version": 1, "status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "equal" else 1


if __name__ == "__main__":
    sys.exit(main())

