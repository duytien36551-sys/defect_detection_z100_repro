#!/usr/bin/env python3
"""Audit structure and arithmetic in an explicit detection quality report."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path


def _integer(value, where, issues):
    if type(value) is not int or value < 0:
        issues.append("{} must be a non-negative integer".format(where))
        return None
    return value


def _number(value, where, issues, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        issues.append("{} must be a finite number".format(where))
        return None
    value = float(value)
    if low is not None and value < low or high is not None and value > high:
        issues.append("{} is outside the allowed range".format(where))
        return None
    return value


def _ratio(num, den):
    return None if den == 0 else num / den


def _sha256(value, where, issues):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        issues.append("{} must be a 64-character hexadecimal SHA-256".format(where))
        return False
    return True


def audit(report):
    issues, warnings, derived = [], [], []
    if not isinstance(report, dict):
        return {"schema_version": 1, "status": "invalid", "issues": ["root must be an object"]}
    if report.get("schema_version") != 1:
        issues.append("schema_version must be 1")
    required_classes = report.get("required_classes")
    if not isinstance(required_classes, list) or not required_classes or any(not isinstance(x, str) or not x for x in required_classes):
        issues.append("required_classes must be a non-empty list of non-empty names")
        required_classes = []
    elif len(set(required_classes)) != len(required_classes):
        issues.append("required_classes contains duplicate names")
    evaluations = report.get("evaluations")
    if not isinstance(evaluations, list) or not evaluations:
        issues.append("evaluations must be a non-empty list")
        evaluations = []
    ids = {}
    for i, ev in enumerate(evaluations):
        p = "evaluations[{}]".format(i)
        if not isinstance(ev, dict):
            issues.append(p + " must be an object")
            continue
        for field in ("id", "split", "backend", "model_sha256", "source_weight_sha256", "dataset_sha256", "protocol_id"):
            if not isinstance(ev.get(field), str) or not ev[field]:
                issues.append("{}.{} must be a non-empty string".format(p, field))
        for field in ("model_sha256", "source_weight_sha256", "dataset_sha256"):
            _sha256(ev.get(field), p + "." + field, issues)
        if isinstance(ev.get("id"), str):
            if ev["id"] in ids:
                issues.append("duplicate evaluation id: " + ev["id"])
            ids[ev["id"]] = ev
        n_images = _integer(ev.get("images"), p + ".images", issues)
        n_normal = _integer(ev.get("normal_images"), p + ".normal_images", issues)
        if n_images is not None and n_normal is not None and n_normal > n_images:
            issues.append(p + ".normal_images exceeds images")
        classes = ev.get("classes")
        if not isinstance(classes, list):
            issues.append(p + ".classes must be a list")
            classes = []
        by_name = {}
        sums = {k: 0 for k in ("targets", "tp", "fp", "fn")}
        sums_complete = True
        for j, row in enumerate(classes):
            q = "{}.classes[{}]".format(p, j)
            if not isinstance(row, dict):
                issues.append(q + " must be an object")
                continue
            name = row.get("name")
            if not isinstance(name, str) or not name:
                issues.append(q + ".name must be a non-empty string")
                continue
            if name in by_name:
                issues.append(p + " has duplicate class " + name)
            by_name[name] = row
            vals = {}
            for field in ("targets", "tp", "fp", "fn"):
                vals[field] = _integer(row.get(field), q + "." + field, issues)
                if vals[field] is not None:
                    sums[field] += vals[field]
                else:
                    sums_complete = False
            for field in ("ap50", "ap50_95"):
                _number(row.get(field), q + "." + field, issues, 0, 1)
            if all(vals[x] is not None for x in ("targets", "tp", "fn")) and vals["tp"] + vals["fn"] != vals["targets"]:
                issues.append(q + ": tp + fn must equal targets under the declared matching counts")
            if all(vals[x] is not None for x in ("tp", "fp", "fn")):
                derived.append({"evaluation_id": ev.get("id"), "class": name,
                                "precision": _ratio(vals["tp"], vals["tp"] + vals["fp"]),
                                "recall": _ratio(vals["tp"], vals["tp"] + vals["fn"]),
                                "f1": _ratio(2 * vals["tp"], 2 * vals["tp"] + vals["fp"] + vals["fn"])})
        missing, extra = sorted(set(required_classes) - set(by_name)), sorted(set(by_name) - set(required_classes))
        if missing:
            issues.append("{}.classes missing required classes: {}".format(p, ", ".join(missing)))
        if extra:
            issues.append("{}.classes has undeclared classes: {}".format(p, ", ".join(extra)))
        if n_normal == 0:
            warnings.append("{}: normal-image false-positive rate is not evaluable (zero normal images)".format(p))
            derived.append({"evaluation_id": ev.get("id"), "normal_image_false_positive_rate": None,
                            "normal_image_false_positive_rate_status": "not_evaluable"})
        elif n_normal is not None:
            fp_norm = _integer(ev.get("false_positive_normal_images"), p + ".false_positive_normal_images", issues)
            if fp_norm is not None and fp_norm > n_normal:
                issues.append(p + ".false_positive_normal_images exceeds normal_images")
            if fp_norm is not None and fp_norm <= n_normal:
                derived.append({"evaluation_id": ev.get("id"),
                                "normal_image_false_positive_rate": fp_norm / n_normal,
                                "normal_image_false_positive_rate_status": "evaluated"})
        if sums_complete:
            derived.append({"evaluation_id": ev.get("id"), "fixed_micro": {
                "tp": sums["tp"], "fp": sums["fp"], "fn": sums["fn"],
                "precision": _ratio(sums["tp"], sums["tp"] + sums["fp"]),
                "recall": _ratio(sums["tp"], sums["tp"] + sums["fn"]),
                "f1": _ratio(2 * sums["tp"], 2 * sums["tp"] + sums["fp"] + sums["fn"]),
                "targets": sums["targets"]}})
    quant = report.get("quantization_comparison")
    if quant is not None:
        if not isinstance(quant, dict):
            issues.append("quantization_comparison must be an object")
        else:
            a, b = quant.get("float_evaluation_id"), quant.get("quantized_evaluation_id")
            if (not isinstance(a, str) or not isinstance(b, str) or a == b
                    or a not in ids or b not in ids):
                issues.append("quantization comparison requires two different known evaluation ids")
            else:
                left, right = ids[a], ids[b]
                float_backend = str(left.get("backend", "")).lower() in {"float", "float32", "fp32"}
                quant_backend = str(right.get("backend", "")).lower() in {"int8", "int8-reference", "quantized", "quantized-int8"}
                if not float_backend or not quant_backend:
                    issues.append("quantization comparison must reference a float evaluation followed by an INT8/quantized evaluation")
                keys = ("source_weight_sha256", "dataset_sha256", "protocol_id", "split")
                comparable = all(isinstance(left.get(k), str) and bool(left.get(k))
                                 and isinstance(right.get(k), str) and bool(right.get(k))
                                 and left.get(k) == right.get(k) for k in keys)
                comparable = comparable and all(
                    re.fullmatch(r"[0-9a-fA-F]{64}", str(ev.get(k, ""))) is not None
                    for ev in (left, right) for k in ("source_weight_sha256", "dataset_sha256"))
                if comparable and float_backend and quant_backend:
                    ap_l, ap_r = left.get("aggregate_ap50_95"), right.get("aggregate_ap50_95")
                    x = _number(ap_l, "float aggregate_ap50_95", issues, 0, 1)
                    y = _number(ap_r, "quantized aggregate_ap50_95", issues, 0, 1)
                    if x is not None and y is not None:
                        derived.append({"quantization_loss_ap50_95_percentage_points": (x - y) * 100,
                                        "comparison_basis": "same source_weight_sha256, dataset_sha256, protocol_id, split"})
                else:
                    warnings.append("quantization loss not calculated: source weight, dataset, protocol, or split differs")
    status = "invalid" if issues else ("incomplete" if warnings else "audit_pass")
    return {"schema_version": 1, "status": status, "issues": issues, "warnings": warnings,
            "derived": derived,
            "scope": "Structure and arithmetic only; does not establish source-data authenticity, model quality, business acceptance, or board execution."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(json.dumps({"schema_version": 1, "status": "invalid", "issues": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2
    result = audit(data)
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        try:
            if args.output.resolve() == args.report.resolve():
                raise ValueError("--output must not resolve to the input report path")
            args.output.write_text(output, encoding="utf-8")
        except (OSError, RuntimeError, ValueError) as exc:
            print(json.dumps({"schema_version": 1, "status": "invalid",
                              "issues": ["cannot write audit output: {}".format(exc)]},
                             ensure_ascii=False, indent=2))
            return 2
    else:
        sys.stdout.write(output)
    return 0 if result["status"] == "audit_pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
