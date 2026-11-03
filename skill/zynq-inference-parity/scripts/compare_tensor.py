#!/usr/bin/env python3
"""Compare two raw tensor files under an explicit numeric contract."""
import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

TYPES = {"f32": ("f", 4), "f64": ("d", 8), "i8": ("b", 1), "u8": ("B", 1),
         "i16": ("h", 2), "u16": ("H", 2), "i32": ("i", 4), "u32": ("I", 4)}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_number(value):
    return value if not isinstance(value, float) or math.isfinite(value) else str(value)


def compare(a_path, b_path, dtype, endian, shape, atol, rtol, allow_padding=False, padding_byte=None):
    if dtype not in TYPES or endian not in ("little", "big"):
        raise ValueError("unsupported dtype or byte order")
    if not shape or any(type(x) is not int or x <= 0 for x in shape):
        raise ValueError("shape dimensions must be positive integers")
    if atol < 0 or rtol < 0 or not math.isfinite(atol) or not math.isfinite(rtol):
        raise ValueError("atol and rtol must be finite and nonnegative")
    fmt, width = TYPES[dtype]
    count = math.prod(shape)
    logical_bytes = count * width
    a, b = Path(a_path).read_bytes(), Path(b_path).read_bytes()
    if len(a) < logical_bytes or len(b) < logical_bytes:
        raise ValueError("input shorter than shape*dtype logical tensor size")
    ap, bp = a[logical_bytes:], b[logical_bytes:]
    if ap or bp:
        if not allow_padding or padding_byte is None:
            raise ValueError("trailing bytes require --allow-padding and --padding-byte")
        if len(ap) != len(bp) or any(x != padding_byte for x in ap + bp):
            raise ValueError("padding length or byte value violates declared contract")
    prefix = "<" if endian == "little" else ">"
    values_a = struct.unpack(prefix + str(count) + fmt, a[:logical_bytes])
    values_b = struct.unpack(prefix + str(count) + fmt, b[:logical_bytes])
    mismatches, max_abs, max_rel, first = 0, 0.0, 0.0, None
    nonfinite = []
    for i, (x, y) in enumerate(zip(values_a, values_b)):
        if isinstance(x, float) and (not math.isfinite(x) or not math.isfinite(y)):
            nonfinite.append(i)
            same = False
        else:
            delta = abs(x-y)
            rel = delta / max(abs(x), abs(y), 1e-300)
            max_abs, max_rel = max(max_abs, delta), max(max_rel, rel)
            same = delta <= atol + rtol * abs(x)
        if not same:
            mismatches += 1
            if first is None:
                first = {"flat_index": i, "reference": json_number(x), "observed": json_number(y)}
    return {"schema_version": 1, "status": "within_tolerance" if not mismatches else "different",
            "interpretation": "Numeric tensor comparison only; it does not establish model quality or deployment acceptance.",
            "contract": {"dtype": dtype, "byte_order": endian, "shape": shape, "atol": atol, "rtol": rtol,
                         "logical_bytes": logical_bytes, "padding_bytes": len(ap), "padding_byte": padding_byte},
            "reference": {"path": str(a_path), "bytes": len(a), "sha256": digest(a), "logical_sha256": digest(a[:logical_bytes])},
            "observed": {"path": str(b_path), "bytes": len(b), "sha256": digest(b), "logical_sha256": digest(b[:logical_bytes])},
            "elements": count, "mismatched_elements": mismatches,
            "max_absolute_error": json_number(max_abs), "max_relative_error": json_number(max_rel),
            "nonfinite_element_indices": nonfinite, "first_mismatch": first}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("reference"); p.add_argument("observed")
    p.add_argument("--dtype", required=True, choices=sorted(TYPES))
    p.add_argument("--byte-order", required=True, choices=["little", "big"])
    p.add_argument("--shape", required=True, help="comma-separated positive dimensions, e.g. 1,3,224,224")
    p.add_argument("--atol", type=float, default=0.0); p.add_argument("--rtol", type=float, default=0.0)
    p.add_argument("--allow-padding", action="store_true")
    p.add_argument("--padding-byte", type=lambda x: int(x, 0), help="required with padding, 0..255")
    args = p.parse_args(argv)
    try:
        shape = [int(x) for x in args.shape.split(",")]
        if args.padding_byte is not None and not 0 <= args.padding_byte <= 255:
            raise ValueError("padding byte must be 0..255")
        result = compare(args.reference, args.observed, args.dtype, args.byte_order, shape,
                         args.atol, args.rtol, args.allow_padding, args.padding_byte)
    except (OSError, ValueError, OverflowError, struct.error) as exc:
        print(json.dumps({"schema_version": 1, "status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"] == "within_tolerance" else 1


if __name__ == "__main__":
    sys.exit(main())
