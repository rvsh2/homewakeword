#!/usr/bin/env bash
set -euo pipefail

OPTIONS_FILE="/data/options.json"

if [[ "${1:-}" == "serve" ]]; then
  shift
fi

if [[ "$#" -gt 0 ]]; then
  exec python -m homewakeword.cli serve "$@"
fi

if [[ -f "$OPTIONS_FILE" ]]; then
  exec python - "$OPTIONS_FILE" <<'PYADDON'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

options_path = Path(sys.argv[1])
options = json.loads(options_path.read_text(encoding="utf-8"))
args = ["python", "-m", "homewakeword.cli", "serve"]
args.extend(["--host", str(options.get("host", "0.0.0.0"))])
args.extend(["--port", str(options.get("port", 10700))])
args.extend(["--detector-backend", str(options.get("detector_backend", "bcresnet"))])
manifest = options.get("manifest")
if manifest:
    args.extend(["--manifest", str(manifest)])
if options.get("custom_models", True):
    args.append("--custom-models")
else:
    args.append("--no-custom-models")
args.extend(["--custom-model-dir", str(options.get("custom_model_dir", "/share/homewakeword/models"))])
if options.get("openwakeword_compat", False):
    args.append("--openwakeword-compat")
else:
    args.append("--no-openwakeword-compat")
args.extend(["--openwakeword-model-dir", str(options.get("openwakeword_model_dir", "/share/openwakeword"))])
if options.get("enable_speex_noise_suppression", False):
    args.append("--enable-speex-noise-suppression")
else:
    args.append("--no-enable-speex-noise-suppression")
if options.get("vad_enabled", False):
    args.append("--vad-enabled")
else:
    args.append("--no-vad-enabled")
args.extend(["--vad-threshold", str(options.get("vad_threshold", 0.5))])
os.execvp(args[0], args)
PYADDON
fi

exec python -m homewakeword.cli serve --host 0.0.0.0 --port 10700 --detector-backend bcresnet --manifest /app/models/bcresnet-real/manifest.yaml --custom-models --custom-model-dir /share/homewakeword/models --no-openwakeword-compat --openwakeword-model-dir /share/openwakeword --enable-speex-noise-suppression --vad-enabled --vad-threshold 0.5
