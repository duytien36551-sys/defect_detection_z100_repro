"""Check the submitted immutable files with Python's standard library."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]

def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()

def main():
    manifest = json.loads((ROOT/'report/submission_sha256.json').read_text(encoding='utf-8'))
    failures = []
    listed = [entry['path'] for entry in manifest['files']]
    if len(listed) != len(set(listed)):
        failures.append('duplicate manifest paths')
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob('*') if p.is_file()
              and p != ROOT/'report/submission_sha256.json'}
    for path in sorted(actual - set(listed)):
        failures.append(path + ': unlisted file')
    for path in ROOT.rglob('*'):
        if not re.fullmatch(r'[a-z0-9_-]+(?:\.[a-z0-9_-]+)*', path.name):
            failures.append(path.relative_to(ROOT).as_posix() + ': invalid name')
    for entry in manifest['files']:
        path = (ROOT/entry['path']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            failures.append(entry['path'] + ': missing or outside package')
        elif path.stat().st_size != entry['bytes'] or sha(path) != entry['sha256']:
            failures.append(entry['path'] + ': changed bytes')
    result = dict(status='PASS_SUBMISSION_HASHES' if not failures else 'FAIL',
                  checked_files=len(manifest['files']), failures=failures,
                  scope='Package integrity only; no compiler, training, board, or accuracy validation')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0

if __name__ == '__main__':
    raise SystemExit(main())
