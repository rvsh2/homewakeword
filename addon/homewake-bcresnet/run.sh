#!/usr/bin/env bash
set -euo pipefail

OPTIONS_FILE="/data/options.json"

if [[ "${1:-}" == "serve" ]]; then
  shift
fi

if [[ "$#" -gt 0 ]]; then
  exec python -m homewake.cli serve "$@"
fi

if [[ -f "$OPTIONS_FILE" ]]; then
  exec python - "$OPTIONS_FILE" <<'PY'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

options_path = Path(sys.argv[1])
options = json.loads(options_path.read_text(encoding='utf-8'))
args = ['python', '-m', 'homewake.cli', 'serve']
args.extend(['--host', str(options.get('host', '0.0.0.0'))])
args.extend(['--port', str(options.get('port', 10700))])
args.extend(['--detector-backend', str(options.get('detector_backend', 'bcresnet'))])
manifest = options.get('manifest')
if manifest:
    args.extend(['--manifest', str(manifest)])
os.execvp(args[0], args)
PY
fi

exec python -m homewake.cli serve --host 0.0.0.0 --port 10700
