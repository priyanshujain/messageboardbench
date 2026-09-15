"""Verify byte preservation of evidence imported from the retired research repo."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    manifest = json.loads((ROOT / 'docs/migration/messageboard-20260908.json').read_text())
    failures = []
    for entry in manifest['files']:
        path = ROOT / entry['path']
        if not path.is_file():
            failures.append({'path': entry['path'], 'reason': 'missing'})
            continue
        data = path.read_bytes()
        if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            failures.append({'path': entry['path'], 'reason': 'bytes changed'})
    print(json.dumps({'checked': len(manifest['files']), 'failures': failures}, indent=2))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
