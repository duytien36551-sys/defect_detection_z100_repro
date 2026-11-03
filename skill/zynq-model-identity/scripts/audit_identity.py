#!/usr/bin/env python3
"""Recompute hashes for an explicit, read-only deployment identity manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def audit(manifest_path: Path) -> tuple[dict, int]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != 1 or not isinstance(data.get("artifacts"), list):
        raise ValueError("expected object with schema_version=1 and artifacts array")
    if not data["artifacts"]:
        raise ValueError("artifacts must contain at least one entry")
    root = manifest_path.resolve().parent
    entries, mismatch, missing_required, names = [], False, False, set()
    for index, item in enumerate(data["artifacts"]):
        if not isinstance(item, dict):
            raise ValueError(f"artifacts[{index}] must be an object")
        name, raw_path = item.get("name"), item.get("path")
        if not isinstance(name, str) or not name.strip() or not isinstance(raw_path, str) or not raw_path:
            raise ValueError(f"artifacts[{index}] requires non-empty string name and path")
        canonical_name = name.strip().casefold()
        if canonical_name in names:
            raise ValueError(f"artifacts[{index}].name duplicates another artifact name")
        names.add(canonical_name)
        path_part = Path(raw_path)
        if path_part.is_absolute():
            raise ValueError(f"artifacts[{index}].path must be relative to the manifest")
        path = (root / path_part).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"artifacts[{index}].path escapes the manifest directory")
        required = item.get("required", True)
        if not isinstance(required, bool):
            raise ValueError(f"artifacts[{index}].required must be boolean")
        declared = item.get("declared_sha256")
        if declared is not None and (not isinstance(declared, str) or not SHA256_RE.fullmatch(declared)):
            raise ValueError(f"artifacts[{index}].declared_sha256 must be 64 hexadecimal characters")
        entry = {"name": name, "path": raw_path, "required": required, "declared_sha256": declared}
        if not path.is_file():
            entry.update(status="missing", actual_sha256=None)
            missing_required |= required
        else:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if declared is None:
                entry.update(status="hashed_only", actual_sha256=actual)
            else:
                is_match = actual.lower() == declared.lower()
                entry.update(status="match" if is_match else "mismatch", actual_sha256=actual)
                mismatch |= not is_match
        entries.append(entry)
    status = "mismatch" if mismatch else "incomplete" if missing_required else "complete"
    result = {"schema_version": 1, "status": status, "manifest": manifest_path.name, "artifacts": entries,
              "interpretation": "Hashes were recomputed from listed files only; this does not prove which files ran on hardware."}
    return result, (1 if mismatch else 3 if missing_required else 0)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result, code = audit(args.manifest)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"schema_version": 1, "status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
