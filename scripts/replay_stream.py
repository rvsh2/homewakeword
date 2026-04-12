from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from homewake.audio import AudioFormatError, iter_wave_chunks
from homewake.detector.bcresnet import BCResNetStreamingFrontend
from homewake.registry import ManifestValidationError, load_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.replay_stream")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expect", required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest, require_artifact=False)
    except ManifestValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    frontend = BCResNetStreamingFrontend(
        audio_config=manifest.audio,
        detector_config=manifest.detector_config(),
    )

    try:
        chunks = iter_wave_chunks(args.input, manifest.audio)
        diagnostics = [frontend.process_chunk(chunk) for chunk in chunks]
    except AudioFormatError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    final = diagnostics[-1]
    payload = {
        "mode": "frontend_only",
        "manifest": str(args.manifest),
        "input": str(args.input),
        "expected": args.expect,
        "wake_word": manifest.wake_word,
        "detection": "none",
        "chunk_count": len(diagnostics),
        "final_chunk_index": final.chunk_index,
        "final_feature_hash": final.feature_hash,
        "final_frame_count": final.frame_count,
        "final_mel_bin_count": final.mel_bin_count,
        "final_padded_left_samples": final.padded_left_samples,
        "final_chunk_rms": round(final.chunk_rms, 6),
        "final_chunk_peak_abs": round(final.chunk_peak_abs, 6),
        "chunk_feature_hashes": [item.feature_hash for item in diagnostics],
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.expect not in {"none", manifest.wake_word}:
        print(
            f"expected must be 'none' or manifest wake word '{manifest.wake_word}', got '{args.expect}'",
            file=sys.stderr,
        )
        return 1
    if args.expect == "none" and payload["detection"] != "none":
        print("frontend-only replay unexpectedly reported a detection", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
