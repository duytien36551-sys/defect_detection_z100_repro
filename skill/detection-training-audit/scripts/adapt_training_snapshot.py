#!/usr/bin/env python3
"""Adapt an archived training-evaluation snapshot into the quality audit schema."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def _finite_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("{} must be a finite number".format(field))
    return float(value)


def read_epochs(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"epoch", "metrics/mAP50-95(B)"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError("results CSV must contain epoch and metrics/mAP50-95(B)")
        rows = []
        for line, row in enumerate(reader, 2):
            try:
                epoch = int(row["epoch"])
            except (TypeError, ValueError):
                raise ValueError("invalid epoch at CSV line {}".format(line))
            score = _finite_number(float(row["metrics/mAP50-95(B)"]), "mAP50-95 at CSV line {}".format(line))
            rows.append({"epoch": epoch, "ap50_95": score})
    if not rows:
        raise ValueError("results CSV has no epoch rows")
    return rows


def adapt(report_path: Path, acceptance_path: Path, split_path: Path, results_path: Path):
    report, acceptance = load_json(report_path), load_json(acceptance_path)
    if not isinstance(report, dict) or not isinstance(acceptance, dict):
        raise ValueError("report and acceptance must be JSON objects")
    completion = report.get("completion")
    if not isinstance(completion, dict):
        raise ValueError("final_report.completion is required")
    best_epoch = completion.get("best_epoch")
    best_sha = report.get("best_sha256")
    if type(best_epoch) is not int or best_epoch < 1:
        raise ValueError("completion.best_epoch must be a positive integer")
    selection_rule = completion.get("best_selection")
    completed_epochs = completion.get("completed_epochs")
    if not isinstance(selection_rule, str) or not selection_rule.strip():
        raise ValueError("completion.best_selection must state the frozen selection rule")
    if type(completed_epochs) is not int or completed_epochs < 1:
        raise ValueError("completion.completed_epochs must be a positive integer")
    if not isinstance(best_sha, str) or len(best_sha) != 64 or any(c not in "0123456789abcdefABCDEF" for c in best_sha):
        raise ValueError("best_sha256 must be 64 hexadecimal characters")
    val = report.get("validation")
    if not isinstance(val, dict) or not isinstance(val.get("per_class"), list) or not val["per_class"]:
        raise ValueError("validation.per_class must be a non-empty list")
    if not isinstance(split_path, Path) or not split_path.is_file():
        raise ValueError("split manifest file is required")
    # Parse the split snapshot to reject malformed source input. Its digest is recorded as
    # the split-manifest identity, never represented as a digest of the underlying images.
    split_doc = load_json(split_path)
    if not isinstance(split_doc, list):
        raise ValueError("split manifest must be a JSON array")
    if not split_doc or any(not isinstance(row, dict) for row in split_doc):
        raise ValueError("split manifest must contain object records")

    epochs = read_epochs(results_path)
    epoch_ids = [row["epoch"] for row in epochs]
    if len(set(epoch_ids)) != len(epoch_ids):
        raise ValueError("results CSV contains duplicate epoch numbers")
    contiguous = epoch_ids == list(range(1, completed_epochs + 1))
    max_score = max(row["ap50_95"] for row in epochs)
    csv_max_epochs = [row["epoch"] for row in epochs if row["ap50_95"] == max_score]
    acceptance_matches = (
        acceptance.get("best_epoch") == best_epoch
        and acceptance.get("best_sha256") == best_sha
        and acceptance.get("both_evaluations_same_frozen_weight") is True
        and acceptance.get("test_used") is False
        and acceptance.get("status") == "passed"
        and acceptance.get("continuous_epochs_1_to_200") is True
        and acceptance.get("no_epoch_201_completed") is True
    )
    split_digest = sha256(split_path)
    validation_rows = []
    class_names = []
    for index, row in enumerate(val["per_class"]):
        if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]:
            raise ValueError("validation.per_class[{}] requires a class name".format(index))
        class_names.append(row["name"])
        for key in ("targets", "tp", "fp", "fn"):
            if type(row.get(key)) is not int or row[key] < 0:
                raise ValueError("validation.per_class[{}].{} must be a nonnegative integer".format(index, key))
        validation_rows.append({
            "name": row["name"], "targets": row["targets"], "tp": row["tp"], "fp": row["fp"], "fn": row["fn"],
            "ap50": _finite_number(row.get("ap50"), "{}.ap50".format(row["name"])),
            "ap50_95": _finite_number(row.get("ap50_95"), "{}.ap50_95".format(row["name"])),
        })
    if len(set(class_names)) != len(class_names):
        raise ValueError("validation.per_class contains duplicate class names")
    class_totals = {key: sum(row[key] for row in validation_rows) for key in ("targets", "tp", "fp", "fn")}

    evaluation_config = val.get("evaluation")
    fixed = val.get("fixed_point")
    if not isinstance(evaluation_config, dict) or not isinstance(fixed, dict):
        raise ValueError("validation.evaluation and validation.fixed_point are required")
    fixed_counts = {key: fixed.get(key) for key in ("tp", "fp", "fn")}
    fixed_counts_valid = all(type(value) is int and value >= 0 for value in fixed_counts.values())
    fixed_counts_match = fixed_counts_valid and all(class_totals[key] == fixed_counts[key] for key in fixed_counts)
    metrics_match = False
    if fixed_counts_valid:
        expected_metrics = {
            "precision": None if fixed["tp"] + fixed["fp"] == 0 else fixed["tp"] / (fixed["tp"] + fixed["fp"]),
            "recall": None if fixed["tp"] + fixed["fn"] == 0 else fixed["tp"] / (fixed["tp"] + fixed["fn"]),
            "f1": None if 2 * fixed["tp"] + fixed["fp"] + fixed["fn"] == 0 else
                 2 * fixed["tp"] / (2 * fixed["tp"] + fixed["fp"] + fixed["fn"]),
        }
        metrics_match = all(
            (expected is None and fixed.get(key) is None)
            or (expected is not None and isinstance(fixed.get(key), (int, float))
                and not isinstance(fixed.get(key), bool)
                and math.isclose(fixed[key], expected, rel_tol=1e-8, abs_tol=1e-10))
            for key, expected in expected_metrics.items())
    val_targets_match = type(val.get("targets")) is int and val.get("targets") == class_totals["targets"]
    manifest_split_counts = Counter(row.get("split") for row in split_doc if isinstance(row.get("split"), str))
    val_images_match_manifest = manifest_split_counts.get("val", 0) == val.get("images")
    known_protocol = {
        "evaluation": evaluation_config,
        "fixed_point": {key: fixed.get(key) for key in (
            "confidence", "nms_iou", "match_iou", "max_det", "matching", "classes_filtered")},
    }
    protocol_bytes = json.dumps(known_protocol, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    protocol_fingerprint = hashlib.sha256(protocol_bytes).hexdigest()

    quality_input = {
        "schema_version": 1,
        "required_classes": class_names,
        "evaluations": [{
            "id": "frozen-validation",
            "split": "validation",
            "backend": "float32",
            "model_sha256": best_sha.lower(),
            "source_weight_sha256": best_sha.lower(),
            "dataset_sha256": split_digest,
            "protocol_id": protocol_fingerprint,
            "images": val.get("images"),
            "normal_images": val.get("normal_images"),
            "false_positive_normal_images": fixed.get("normal_false_images"),
            "aggregate_ap50": val.get("ap50"),
            "aggregate_ap50_95": val.get("ap50_95"),
            "classes": validation_rows,
        }],
    }
    script = Path(__file__).with_name("audit_quality_report.py")
    spec = importlib.util.spec_from_file_location("audit_quality_report", script)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    quality_audit = module.audit(quality_input)
    issues = list(quality_audit.get("issues", [])) if quality_audit.get("status") == "invalid" else []

    checks = {
        "epochs_contiguous_1_to_n": contiguous,
        "csv_row_count": len(epochs),
        "csv_row_count_matches_completed_epochs": len(epochs) == completed_epochs,
        "csv_max_ap50_95_epochs": csv_max_epochs,
        "declared_best_epoch": best_epoch,
        "csv_max_agrees_with_declared_best": best_epoch in csv_max_epochs,
        "acceptance_identity_and_frozen_eval_match": acceptance_matches,
        "best_selection_rule": selection_rule,
        "acceptance_claims_split_manifest_unchanged": acceptance.get("split_manifest_unchanged") is True,
        "declared_completed_epochs": completed_epochs,
        "no_test_used_claim": completion.get("test_used") is False and acceptance.get("test_used") is False,
        "per_class_targets_sum_matches_report": val_targets_match,
        "per_class_tp_fp_fn_sum_matches_report": fixed_counts_match,
        "fixed_micro_precision_recall_f1_match_report": metrics_match,
        "validation_image_count_matches_manifest_rows": val_images_match_manifest,
        "split_manifest_rows_by_split": dict(manifest_split_counts),
    }
    for key, ok in (("csv_max_agrees_with_declared_best", checks["csv_max_agrees_with_declared_best"]),
                    ("acceptance_identity_and_frozen_eval_match", acceptance_matches),
                    ("epochs_contiguous_1_to_n", contiguous),
                    ("csv_row_count_matches_completed_epochs", checks["csv_row_count_matches_completed_epochs"]),
                    ("acceptance_claims_split_manifest_unchanged", checks["acceptance_claims_split_manifest_unchanged"]),
                    ("no_test_used_claim", checks["no_test_used_claim"]),
                    ("per_class_targets_sum_matches_report", val_targets_match),
                    ("per_class_tp_fp_fn_sum_matches_report", fixed_counts_match),
                    ("fixed_micro_precision_recall_f1_match_report", metrics_match),
                    ("validation_image_count_matches_manifest_rows", val_images_match_manifest)):
        if not ok:
            issues.append(key)
    sources = []
    for role, path in (("final_report", report_path), ("final_acceptance", acceptance_path),
                       ("split_manifest", split_path), ("training_results_csv", results_path)):
        sources.append({"role": role, "path": str(path), "sha256_recomputed": sha256(path), "bytes": path.stat().st_size})
    missing = []
    if val.get("normal_images") == 0:
        missing.append("normal-image false-positive rate is not evaluable because normal_images=0")
    if report.get("test_used") is False:
        missing.append("test-set evaluation is intentionally absent; no test score is inferred")
    if report.get("int8_evaluated") is False:
        missing.append("INT8 evaluation is absent")
    if report.get("board_evaluated") is False:
        missing.append("board evaluation is absent")
    missing.append("weight file is not included in this fixture; best_sha256 is a report claim and was not recomputed")
    missing.append("split-manifest digest identifies the manifest snapshot only, not image or label payloads")
    missing.append("protocol fingerprint covers recorded evaluation/fixed-point fields only; it does not establish full evaluator provenance")
    status = "source_consistency_issue" if issues or quality_audit["status"] == "invalid" else "computed_with_limitations"
    return {
        "schema_version": 1,
        "status": status,
        "source_files": sources,
        "field_mapping": {
            "model_sha256/source_weight_sha256": "final_report.best_sha256 (declared; weight absent)",
            "dataset_sha256": "SHA-256 of split_manifest.json bytes (manifest identity only)",
            "protocol_id": "SHA-256 of the recorded evaluation and fixed-point settings (partial fingerprint)",
            "required_classes/classes": "validation.per_class ordered rows; AP and fixed-point TP/FP/FN kept per class",
            "images/normal_images": "validation.images / validation.normal_images",
            "backend/split": "fixed adapter labels float32 / validation",
            "results_csv": "epoch and metrics/mAP50-95(B) only; used to cross-check declared selection, never to reselect",
        },
        "selection_and_integrity_checks": checks,
        "issues": issues,
        "missing_or_unverified": missing,
        "quality_report_input": quality_input,
        "quality_report_audit": quality_audit,
        "scope": "This adapter checks an archived report snapshot and recomputable arithmetic. It does not run or reselect training, recalculate AP, prove source-data independence, validate the declared checkpoint bytes, or establish test/INT8/board/business acceptance.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--acceptance", required=True, type=Path)
    parser.add_argument("--split-manifest", required=True, type=Path)
    parser.add_argument("--results-csv", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = adapt(args.report, args.acceptance, args.split_manifest, args.results_csv)
        encoded = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            if args.output.resolve() in {p.resolve() for p in (args.report, args.acceptance, args.split_manifest, args.results_csv)}:
                raise ValueError("output path must not overwrite an input source")
            args.output.write_text(encoded, encoding="utf-8")
        else:
            sys.stdout.write(encoded)
    except (OSError, UnicodeError, json.JSONDecodeError, csv.Error, ValueError, TypeError) as exc:
        print(json.dumps({"schema_version": 1, "status": "invalid_input", "error": str(exc)}, ensure_ascii=False))
        return 2
    return 1 if result["status"] == "source_consistency_issue" else 0


if __name__ == "__main__":
    raise SystemExit(main())
