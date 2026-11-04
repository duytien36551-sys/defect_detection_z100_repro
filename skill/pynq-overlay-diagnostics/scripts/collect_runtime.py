#!/usr/bin/env python3
"""Collect read-only PYNQ runtime identity and overlay metadata as JSON.

The collector asks PYNQ to parse the explicitly supplied bitstream with
download=False, then reads only Overlay.ip_dict and Overlay.is_loaded(). It
does not access IP driver attributes, MMIO, DMA, buffers, resets, or transfers.
"""

import argparse
import datetime
import hashlib
import importlib
import json
import math
import os
import platform
import sys
from collections.abc import Mapping
from pathlib import Path


_UNSET = object()
_OVERLAY_SOURCE = {
    "version": "PYNQ v3.0.1, upstream commit 93ddd21ab623883590a8c8b07f0b157b2855da4b",
    "url": "https://github.com/Xilinx/PYNQ/blob/93ddd21ab623883590a8c8b07f0b157b2855da4b/pynq/overlay.py",
}
_IS_LOADED_SOURCE = {
    "version": "PYNQ v3.0.1, upstream commit 93ddd21ab623883590a8c8b07f0b157b2855da4b",
    "url": "https://github.com/Xilinx/PYNQ/blob/93ddd21ab623883590a8c8b07f0b157b2855da4b/pynq/overlay.py",
}


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact(path):
    if path is None:
        return None, None
    supplied = os.fspath(path)
    try:
        resolved = Path(supplied).resolve(strict=True)
        if not resolved.is_file():
            raise OSError("path is not a regular file")
        return {
            "supplied_path": supplied,
            "resolved_path": str(resolved),
            "sha256": _sha256(resolved),
        }, None
    except (OSError, ValueError, TypeError) as exc:
        return {"supplied_path": supplied, "resolved_path": None, "sha256": None}, exc


def _hwh_artifact(bit_path, hwh_path):
    if hwh_path is not None:
        artifact, error = _artifact(hwh_path)
        artifact["selection"] = "explicit_path"
        artifact["consumption_claim"] = False
        return artifact, error

    candidate = Path(bit_path).with_suffix(".hwh")
    if not candidate.exists():
        return {
            "selection": "adjacent_candidate",
            "candidate_path": str(candidate),
            "state": "candidate_not_found",
            "resolved_path": None,
            "sha256": None,
            "consumption_claim": False,
        }, None
    artifact, error = _artifact(candidate)
    artifact["selection"] = "adjacent_candidate"
    artifact["candidate_path"] = str(candidate)
    artifact["consumption_claim"] = False
    return artifact, error


def _json_safe(value, active=None, depth=0):
    """Convert metadata values to JSON without traversing arbitrary objects."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else {"non_finite_float": repr(value)}
    if depth >= 32:
        return {"truncated": True, "reason": "metadata nesting limit"}
    if active is None:
        active = set()
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            return {"omitted": "cyclic reference"}
        active.add(identity)
        try:
            return {str(key): _json_safe(item, active, depth + 1) for key, item in value.items()}
        finally:
            active.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active:
            return {"omitted": "cyclic reference"}
        active.add(identity)
        try:
            return [_json_safe(item, active, depth + 1) for item in value]
        finally:
            active.remove(identity)
    kind = type(value)
    return {"non_json_value_type": "{}.{}".format(kind.__module__, kind.__qualname__)}


def _version(module):
    try:
        value = module.__version__
    except Exception as exc:
        return None, {"state": "not_observed", "error": _error_details(exc)}
    if value is None:
        return None, {"state": "not_exposed"}
    try:
        return str(value), {"state": "observed", "source": "module.__version__"}
    except Exception as exc:
        return None, {"state": "not_observed", "error": _error_details(exc)}


def _error_details(exc):
    return {"type": type(exc).__name__, "message": str(exc)}


def _load_optional(name, injected, importer):
    if injected is not _UNSET:
        return injected, {"state": "injected_simulation"}
    try:
        return importer(name), {"state": "imported_at_runtime"}
    except ModuleNotFoundError as exc:
        state = "unavailable" if exc.name == name else "error"
        return None, {"state": state, "error": _error_details(exc)}
    except Exception as exc:
        return None, {"state": "error", "error": _error_details(exc)}


def _new_report(bit_info, hwh_info, simulated):
    runtime = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
    }
    if "BOARD" in os.environ:
        runtime["BOARD"] = os.environ["BOARD"]
    return {
        "schema_version": 1,
        "status": "error",
        "collection_context": "injected_dependencies_simulation" if simulated else "runtime",
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "runtime": runtime,
        "versions": {"pynq": None, "numpy": None},
        "dependencies": {},
        "artifacts": {
            "bit": bit_info,
            "hwh": hwh_info,
            "hwh_note": "An HWH hash records the explicit file or adjacent candidate only; it does not prove Overlay consumed that file. Overlay receives only the bitstream path.",
        },
        "hardware_actions": {
            "overlay_download_requested": False,
            "mmio_write_dma_reset_buffer_allocation_or_transfer_requested": False,
            "functional_outputs_verified": False,
        },
        "overlay": {
            "constructed": False,
            "constructor": {"call": "pynq.Overlay(str(bit), download=False)", "download": False},
            "ip_dict": None,
            "register_metadata": None,
            "is_loaded": {
                "method": "Overlay.is_loaded()",
                "observed": False,
                "value": None,
                "interpretation": "A true value is PYNQ's bitstream-identity check; it does not verify outputs or workload correctness.",
                "source": _IS_LOADED_SOURCE,
            },
            "source": _OVERLAY_SOURCE,
        },
        "errors": [],
    }


def collect_runtime(bit_path, hwh_path=None, *, pynq_module=_UNSET,
                    numpy_module=_UNSET, import_module=None):
    """Collect a report. Dependency arguments exist for simulation-only tests."""
    bit_info, bit_error = _artifact(bit_path)
    hwh_info, hwh_error = _hwh_artifact(bit_path, hwh_path)
    simulated = pynq_module is not _UNSET or numpy_module is not _UNSET
    report = _new_report(bit_info, hwh_info, simulated)
    if bit_error is not None:
        report["errors"].append({"stage": "bit_file", **_error_details(bit_error)})
    if hwh_error is not None:
        report["errors"].append({"stage": "hwh_file", **_error_details(hwh_error)})
    if report["errors"]:
        return report

    importer = import_module or importlib.import_module
    numpy, numpy_state = _load_optional("numpy", numpy_module, importer)
    report["dependencies"]["numpy"] = numpy_state
    if numpy is not None:
        report["versions"]["numpy"], report["dependencies"]["numpy_version"] = _version(numpy)

    pynq, pynq_state = _load_optional("pynq", pynq_module, importer)
    report["dependencies"]["pynq"] = pynq_state
    if pynq is None:
        if pynq_state["state"] == "unavailable":
            report["status"] = "unavailable"
        else:
            report["errors"].append({"stage": "pynq_import", **pynq_state.get("error", {"type": "ImportError", "message": "PYNQ could not be imported"})})
        return report

    report["versions"]["pynq"], report["dependencies"]["pynq_version"] = _version(pynq)
    try:
        overlay_type = pynq.Overlay
        overlay = overlay_type(str(bit_path), download=False)
        report["overlay"]["constructed"] = True
    except Exception as exc:
        report["errors"].append({"stage": "overlay_construction", **_error_details(exc)})
        return report

    try:
        # This is the metadata dictionary, not an IP driver lookup. Do not
        # getattr individual IP names: PYNQ may instantiate drivers on access.
        raw_ip_dict = overlay.ip_dict
        if not isinstance(raw_ip_dict, Mapping):
            raise TypeError("Overlay.ip_dict is not a mapping")
        report["overlay"]["ip_dict"] = _json_safe(raw_ip_dict)
        registers = {}
        without_registers = []
        for name, metadata in raw_ip_dict.items():
            if isinstance(metadata, Mapping) and "registers" in metadata:
                registers[str(name)] = _json_safe(metadata["registers"])
            else:
                without_registers.append(str(name))
        report["overlay"]["register_metadata"] = {
            "source_field": "Overlay.ip_dict[IP]['registers']",
            "by_ip": registers,
            "ips_without_registers_field": without_registers,
        }
    except Exception as exc:
        report["errors"].append({"stage": "ip_dict", **_error_details(exc)})

    try:
        loaded = overlay.is_loaded()
        report["overlay"]["is_loaded"]["observed"] = True
        report["overlay"]["is_loaded"]["value"] = _json_safe(loaded)
        report["overlay"]["is_loaded"]["provenance"] = "Returned by Overlay.is_loaded() after construction with download=False; this is an identity observation, not output verification."
    except Exception as exc:
        report["errors"].append({"stage": "is_loaded", **_error_details(exc)})

    report["status"] = "observed" if not report["errors"] else "error"
    return report


def _paths_alias(left, right):
    try:
        return Path(left).resolve(strict=False) == Path(right).resolve(strict=False)
    except (OSError, ValueError, TypeError):
        return False
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bit", required=True, type=Path, help="explicit bitstream path")
    parser.add_argument("--hwh", type=Path, help="optional explicit HWH path to hash")
    parser.add_argument("--out", required=True, type=Path, help="explicit JSON report path")
    args = parser.parse_args(argv)

    # Refuse aliases before hashing or constructing PYNQ, including missing
    # input paths that would otherwise be overwritten by the report.
    hwh_input = args.hwh if args.hwh is not None else args.bit.with_suffix(".hwh")
    if _paths_alias(args.out, args.bit) or _paths_alias(args.out, hwh_input):
        parser.error("--out must not overwrite the supplied bit or HWH file")
    report = collect_runtime(args.bit, args.hwh)
    try:
        with args.out.open("w", encoding="utf-8", newline="\n") as destination:
            json.dump(report, destination, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
            destination.write("\n")
    except OSError as exc:
        print("cannot write report: {}".format(exc), file=sys.stderr)
        return 1
    if report["status"] == "observed":
        return 0
    if report["status"] == "unavailable":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
