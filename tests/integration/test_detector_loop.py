from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from scripts.replay_stream import DetectorReplayPayload, main


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'stream'
MANIFEST_ROOT = Path(__file__).resolve().parents[1] / 'fixtures' / 'manifests'


def _run_replay(tmp_path: Path, *, manifest: str, input_name: str, expect: str) -> DetectorReplayPayload:
    output_path = tmp_path / f'{Path(input_name).stem}.json'
    exit_code = main([
        '--manifest', str(MANIFEST_ROOT / manifest),
        '--input', str(FIXTURE_ROOT / input_name),
        '--expect', expect,
        '--json-out', str(output_path),
    ])
    assert exit_code == 0
    return cast(DetectorReplayPayload, json.loads(output_path.read_text(encoding='utf-8')))


def test_positive_replay_emits_exactly_one_detection(tmp_path: Path) -> None:
    payload = _run_replay(
        tmp_path,
        manifest='ok_nabu_detector.yaml',
        input_name='ok_nabu_positive.wav',
        expect='ok_nabu',
    )

    assert payload['mode'] == 'detector'
    assert payload['detection'] == 'ok_nabu'
    assert payload['detection_count'] == 1
    assert payload['detected_labels'] == ['ok_nabu']
    assert payload['event_counts']['detection'] == 1
    assert payload['detector_counters']['detections'] == 1
    assert payload['detector_counters']['duplicate_suppressions'] > 0
    assert payload['detector_counters']['cooldown_suppressions'] > 0
    assert payload['detector_counters']['invalid_frames'] == 0
    assert payload['detector_counters']['model_load_failures'] == 0
    assert payload['detector_counters']['runtime_failures'] == 0


def test_negative_replay_emits_zero_detections(tmp_path: Path) -> None:
    payload = _run_replay(
        tmp_path,
        manifest='ok_nabu_detector.yaml',
        input_name='no_wake_negative.wav',
        expect='none',
    )

    assert payload['mode'] == 'detector'
    assert payload['detection'] == 'none'
    assert payload['detection_count'] == 0
    assert payload['detected_labels'] == []
    assert payload['event_counts'].get('detection', 0) == 0
    assert payload['detector_counters']['detections'] == 0
    assert payload['detector_counters']['duplicate_suppressions'] == 0
    assert payload['detector_counters']['invalid_frames'] == 0
    assert payload['detector_counters']['model_load_failures'] == 0
    assert payload['detector_counters']['runtime_failures'] == 0
