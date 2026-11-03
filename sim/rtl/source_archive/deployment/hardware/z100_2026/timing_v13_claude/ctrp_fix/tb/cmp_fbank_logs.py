#!/usr/bin/env python3
"""Compare the transaction logs written by tb_fbank_v13_vs_v13p.

Each log line is "<TAG><index> <field>=<value> ...". The two DUTs write the
same tags with different indexes (0/1) and no cycle stamps, so a line-by-line
comparison of the tag-stripped text is the sequential-equivalence verdict.

Also checks that every transaction type actually occurred, so a log that is
identical only because both sides did nothing cannot pass.
"""
import sys, collections

def load(path):
    rows = []
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        tag, rest = line.split(None, 1)
        rows.append((tag.rstrip("0123456789"), rest))
    return rows

def main(ref, new, require_min=1):
    a, b = load(ref), load(new)
    print(f"ref lines {len(a)}, new lines {len(b)}")
    hist = collections.Counter(t for t, _ in a)
    print("transactions:", dict(sorted(hist.items())))
    missing = [t for t in ('BEGIN','WORD','COMMIT','READ','ERR','OUT') if hist[t] < require_min]
    if missing:
        print("FAIL: transaction types below minimum ->", missing)
        return 1
    n = min(len(a), len(b))
    diffs = 0
    for i in range(n):
        if a[i] != b[i]:
            diffs += 1
            if diffs <= 10:
                print(f"  MISMATCH #{i}: {a[i]} != {b[i]}")
    if len(a) != len(b):
        print(f"FAIL: length {len(a)} != {len(b)}")
        tail = a[n:] or b[n:]
        for row in tail[:5]:
            print("   extra:", row)
        return 1
    if diffs:
        print(f"FAIL: {diffs} mismatching transactions")
        return 1
    print(f"PASS: {n} transactions identical")
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 1))
