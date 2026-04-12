from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sys
from typing import Literal, TypedDict, cast

from homewakeword.audio import AudioFormatError, iter_wave_chunks
from homewakeword.config import HomeWakeWordConfig
from homewakeword.detector.bcresnet import (
    BCResNetDetector,
    BCResNetRuntimeError,
    BCResNetStreamingFrontend,
)
from homewakeword.events import DetectionEventType
from homewakeword.registry import ManifestValidationError, ModelManifest, load_registry
from homewakeword.server.wyoming import WyomingRuntime


@dataclass(frozen=True, slots=True)
class ReplayArgs:
    manifest: Path
    input: Path
    expect: str
    json_out: Path
    wake_word: str | None


class DetectionEventRecord(TypedDict):
    chunk_index: int
    type: str
    label: str
    score: float
    threshold: float
    cooldown_remaining_seconds: float
    refractory_remaining_seconds: float
    armed: bool


class FinalStateRecord(TypedDict):
    cooldown_remaining_seconds: float
    refractory_remaining_seconds: float
    armed: bool


class FrontendReplayPayload(TypedDict):
    mode: Literal['frontend_only']
    manifest: str
    input: str
    expected: str
    wake_word: str
    detection: Literal['none']
    chunk_count: int
    final_chunk_index: int
    final_feature_hash: str
    final_frame_count: int
    final_mel_bin_count: int
    final_padded_left_samples: int
    final_chunk_rms: float
    final_chunk_peak_abs: float
    chunk_feature_hashes: list[str]


class DetectorReplayPayload(TypedDict):
    mode: Literal['detector']
    manifest: str
    input: str
    expected: str
    wake_word: str
    detection: str
    detection_count: int
    detected_labels: list[str]
    chunk_count: int
    event_counts: dict[str, int]
    events: list[DetectionEventRecord]
    detector_counters: dict[str, int]
    final_event_type: str
    final_score: float
    final_state: FinalStateRecord


ReplayPayload = FrontendReplayPayload | DetectorReplayPayload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m scripts.replay_stream')
    _ = parser.add_argument('--manifest', type=Path, required=True)
    _ = parser.add_argument('--input', type=Path, required=True)
    _ = parser.add_argument('--expect', required=True)
    _ = parser.add_argument('--json-out', type=Path, required=True)
    _ = parser.add_argument(
        '--wake-word',
        default=None,
        help='Resolve a specific wake word from a registry pack manifest',
    )
    return parser


def _parse_args(argv: list[str] | None = None) -> ReplayArgs:
    namespace = build_parser().parse_args(argv)
    return ReplayArgs(
        manifest=cast(Path, namespace.manifest),
        input=cast(Path, namespace.input),
        expect=cast(str, namespace.expect),
        json_out=cast(Path, namespace.json_out),
        wake_word=cast(str | None, namespace.wake_word),
    )


def _resolve_manifest(args: ReplayArgs) -> ModelManifest:
    registry = load_registry(args.manifest, require_artifact=False)
    if args.wake_word is None:
        return registry.default_model
    return registry.resolve('bcresnet', wake_word=args.wake_word)


def _frontend_payload(
    manifest: ModelManifest,
    args: ReplayArgs,
) -> tuple[int, FrontendReplayPayload | None]:
    frontend = BCResNetStreamingFrontend(
        audio_config=manifest.audio,
        detector_config=manifest.detector_config(),
    )
    try:
        chunks = iter_wave_chunks(args.input, manifest.audio)
        diagnostics = [frontend.process_chunk(chunk) for chunk in chunks]
    except AudioFormatError as exc:
        print(str(exc), file=sys.stderr)
        return 1, None

    final = diagnostics[-1]
    return 0, {
        'mode': 'frontend_only',
        'manifest': str(args.manifest),
        'input': str(args.input),
        'expected': args.expect,
        'wake_word': manifest.wake_word,
        'detection': 'none',
        'chunk_count': len(diagnostics),
        'final_chunk_index': final.chunk_index,
        'final_feature_hash': final.feature_hash,
        'final_frame_count': final.frame_count,
        'final_mel_bin_count': final.mel_bin_count,
        'final_padded_left_samples': final.padded_left_samples,
        'final_chunk_rms': round(final.chunk_rms, 6),
        'final_chunk_peak_abs': round(final.chunk_peak_abs, 6),
        'chunk_feature_hashes': [item.feature_hash for item in diagnostics],
    }


def _detector_payload(
    manifest: ModelManifest,
    args: ReplayArgs,
) -> tuple[int, DetectorReplayPayload | None]:
    detector = BCResNetDetector(
        config=manifest.detector_config(),
        manifest=manifest,
        audio_config=manifest.audio,
    )
    runtime = WyomingRuntime(
        config=HomeWakeWordConfig(audio=manifest.audio, detector=manifest.detector_config()),
        detector=detector,
    )
    try:
        detector.open()
        chunks = iter_wave_chunks(args.input, manifest.audio)
        events = [runtime.handle_audio_chunk(chunk) for chunk in chunks]
    except (AudioFormatError, BCResNetRuntimeError, ManifestValidationError) as exc:
        print(str(exc), file=sys.stderr)
        return 1, None
    finally:
        detector.close()

    event_counts = dict(sorted(Counter(event.type.value for event in events).items()))
    detections = [event for event in events if event.type is DetectionEventType.DETECTION]
    final = events[-1]
    counters_raw = asdict(detector.counters)
    counters = {str(key): int(value) for key, value in counters_raw.items()}
    return 0, {
        'mode': 'detector',
        'manifest': str(args.manifest),
        'input': str(args.input),
        'expected': args.expect,
        'wake_word': manifest.wake_word,
        'detection': detections[0].label if len(detections) == 1 else ('none' if not detections else 'multiple'),
        'detection_count': len(detections),
        'detected_labels': [event.label for event in detections],
        'chunk_count': len(events),
        'event_counts': event_counts,
        'events': [
            {
                'chunk_index': index,
                'type': event.type.value,
                'label': event.label,
                'score': event.decision.score,
                'threshold': event.decision.threshold,
                'cooldown_remaining_seconds': event.decision.state.cooldown_remaining_seconds,
                'refractory_remaining_seconds': event.decision.state.refractory_remaining_seconds,
                'armed': event.decision.state.armed,
            }
            for index, event in enumerate(events, start=1)
            if event.type is DetectionEventType.DETECTION
        ],
        'detector_counters': counters,
        'final_event_type': final.type.value,
        'final_score': final.decision.score,
        'final_state': {
            'cooldown_remaining_seconds': final.decision.state.cooldown_remaining_seconds,
            'refractory_remaining_seconds': final.decision.state.refractory_remaining_seconds,
            'armed': final.decision.state.armed,
        },
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        manifest = _resolve_manifest(args)
    except (ManifestValidationError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    payload: ReplayPayload
    if args.expect not in {'none', manifest.wake_word}:
        print(
            f"expected must be 'none' or manifest wake word '{manifest.wake_word}', got '{args.expect}'",
            file=sys.stderr,
        )
        return 1

    if manifest.mode == 'frontend_only':
        exit_code, frontend_payload = _frontend_payload(manifest, args)
        if exit_code != 0 or frontend_payload is None:
            return exit_code
        if args.expect == 'none' and frontend_payload['detection'] != 'none':
            print('frontend-only replay unexpectedly reported a detection', file=sys.stderr)
            return 1
        payload = frontend_payload
    else:
        exit_code, detector_payload = _detector_payload(manifest, args)
        if exit_code != 0 or detector_payload is None:
            return exit_code
        if args.expect == 'none' and detector_payload['detection_count'] != 0:
            print('detector replay unexpectedly reported a detection', file=sys.stderr)
            return 1
        if args.expect != 'none' and (
            detector_payload['detection_count'] != 1
            or detector_payload['detected_labels'] != [manifest.wake_word]
        ):
            print('detector replay did not emit exactly one expected detection', file=sys.stderr)
            return 1
        payload = detector_payload

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )
    return 0


if __name__ == '__main__':
    _ = main()
    raise SystemExit(_)
