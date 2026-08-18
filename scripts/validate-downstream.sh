#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 -m py_compile "$ROOT/scripts/generate_release_feeds.py"
python3 "$ROOT/scripts/documentation_health.py" --check
python3 - "$ROOT" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for path in sorted((root / "JSON").glob("*.json")):
    json.loads(path.read_text(encoding="utf-8"))
PY

printf 'APEX downstream validation passed\n'
