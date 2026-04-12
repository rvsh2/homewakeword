from __future__ import annotations

import argparse
from pathlib import Path
import sys

from homewake.detector.bcresnet import BCResNetDetector, BCResNetRuntimeError
from homewake.registry import ManifestValidationError, load_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.validate_startup")
    parser.add_argument("--manifest", type=Path, required=True)
    return parser


def validate_startup(manifest_path: Path) -> str:
    manifest = load_registry(manifest_path, require_artifact=True).resolve("bcresnet")
    detector = BCResNetDetector(
        config=manifest.detector_config(),
        manifest=manifest,
        audio_config=manifest.audio,
    )
    detector.open()
    detector.close()
    model_path = manifest.model_path if manifest.model_path is not None else "<none>"
    return (
        f"startup validation passed: backend={manifest.backend} "
        f"framework={manifest.framework} model={model_path}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(validate_startup(args.manifest))
    except (ManifestValidationError, BCResNetRuntimeError, LookupError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
