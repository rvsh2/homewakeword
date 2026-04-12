from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import yaml

from homewake.audio import AudioFormatError, iter_wave_chunks
from homewake.config import AudioInputConfig, DetectorConfig, LogMelFrontendConfig
from homewake.detector.bcresnet import BCResNetStreamingFrontend


def _load_manifest(path: Path) -> tuple[AudioInputConfig, DetectorConfig, str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    audio_data = data.get("audio", {})
    frontend_data = data.get("frontend", {})
    wake_word = data.get("wake_word", "frontend_only")

    audio_config = AudioInputConfig(
        sample_rate_hz=int(audio_data.get("sample_rate_hz", 16_000)),
        sample_width_bytes=int(audio_data.get("sample_width_bytes", 2)),
        channels=int(audio_data.get("channels", 1)),
        frame_samples=int(audio_data.get("frame_samples", 1_280)),
        window_seconds=float(audio_data.get("window_seconds", 1.0)),
    )
    detector_config = DetectorConfig(
        threshold=float(data.get("threshold", 1.0)),
        frontend=LogMelFrontendConfig(
            n_fft=int(frontend_data.get("n_fft", 512)),
            win_length=int(frontend_data.get("win_length", 480)),
            hop_length=int(frontend_data.get("hop_length", 160)),
            n_mels=int(frontend_data.get("n_mels", 40)),
            f_min_hz=float(frontend_data.get("f_min_hz", 20.0)),
            f_max_hz=float(frontend_data.get("f_max_hz", 7_600.0)),
            log_floor=float(frontend_data.get("log_floor", 1e-6)),
            context_seconds=float(frontend_data.get("context_seconds", 1.0)),
        ),
    )
    return audio_config, detector_config, wake_word


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.replay_stream")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expect", required=True)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    audio_config, detector_config, wake_word = _load_manifest(args.manifest)
    frontend = BCResNetStreamingFrontend(
        audio_config=audio_config,
        detector_config=detector_config,
    )

    try:
        chunks = iter_wave_chunks(args.input, audio_config)
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
        "wake_word": wake_word,
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

    if args.expect not in {"none", wake_word}:
        print(
            f"expected must be 'none' or manifest wake word '{wake_word}', got '{args.expect}'",
            file=sys.stderr,
        )
        return 1
    if args.expect == "none" and payload["detection"] != "none":
        print("frontend-only replay unexpectedly reported a detection", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
