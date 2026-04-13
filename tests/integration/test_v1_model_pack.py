from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from homewakeword.config import (
    DetectorConfig,
    HomeWakeWordConfig,
    VADConfig,
    WyomingServerConfig,
)
from homewakeword.runtime import build_service
from scripts.replay_stream import DetectorReplayPayload, main


FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures"
REPO_PACK_MANIFEST = Path(__file__).resolve().parents[2] / "models" / "manifest.yaml"
FIXTURE_PACK_MANIFEST = FIXTURE_ROOT / "manifests" / "v1_pack.yaml"
UNVALIDATED_PACK_MANIFEST = FIXTURE_ROOT / "manifests" / "v1_pack_with_unvalidated.yaml"
EXPECTED_V1_WAKE_WORDS = (
    "okay_nabu",
    "hey_jarvis",
    "alexa",
    "hey_mycroft",
    "hey_rhasspy",
)


def _build_service(manifest_path: Path):
    return build_service(
        HomeWakeWordConfig(
            detector=DetectorConfig(
                manifest_path=manifest_path,
                enable_speex_noise_suppression=False,
                vad=VADConfig(enabled=False),
            ),
            server=WyomingServerConfig(host="127.0.0.1", port=10400),
        )
    )


def _run_replay(
    tmp_path: Path,
    *,
    manifest_path: Path,
    wake_word: str,
    input_name: str,
    expect: str,
) -> DetectorReplayPayload:
    output_path = tmp_path / f"{wake_word}-{Path(input_name).stem}.json"
    exit_code = main(
        [
            "--manifest",
            str(manifest_path),
            "--wake-word",
            wake_word,
            "--input",
            str(FIXTURE_ROOT / "stream" / input_name),
            "--expect",
            expect,
            "--json-out",
            str(output_path),
        ]
    )
    assert exit_code == 0
    return cast(
        DetectorReplayPayload, json.loads(output_path.read_text(encoding="utf-8"))
    )


def test_runtime_advertises_only_validated_v1_pack_entries() -> None:
    service = _build_service(REPO_PACK_MANIFEST)

    assert service.manifest.wake_word == "okay_nabu"
    assert service.registry.list_wake_words() == EXPECTED_V1_WAKE_WORDS
    assert [
        wake_word.name for wake_word in service.server.describe().wake_words
    ] == list(EXPECTED_V1_WAKE_WORDS)
    assert len(service.inventory) == len(EXPECTED_V1_WAKE_WORDS)

    inventory = {
        record.wake_word: record.as_report_dict() for record in service.inventory
    }
    assert set(inventory) == set(EXPECTED_V1_WAKE_WORDS)
    for wake_word in EXPECTED_V1_WAKE_WORDS:
        record = inventory[wake_word]
        assert record["threshold"] == 0.55
        assert record["provenance_status"] == "approved"
        assert record["evaluation_status"] == "validated"
        assert record["hash_verified"] is True
        assert record["release_approved"] is True
        assert record["advertised"] is True
        assert record["positive_fixture"] == f"{wake_word}_positive.wav"
        assert record["negative_fixture"] == f"{wake_word}_negative.wav"


def test_fixture_pack_replays_positive_and_negative_for_each_v1_wake_word(
    tmp_path: Path,
) -> None:
    for wake_word in EXPECTED_V1_WAKE_WORDS:
        positive_payload = _run_replay(
            tmp_path,
            manifest_path=FIXTURE_PACK_MANIFEST,
            wake_word=wake_word,
            input_name=f"{wake_word}_positive.wav",
            expect=wake_word,
        )
        assert positive_payload["mode"] == "detector"
        assert positive_payload["wake_word"] == wake_word
        assert positive_payload["detection"] == wake_word
        assert positive_payload["detection_count"] == 1
        assert positive_payload["detected_labels"] == [wake_word]
        assert positive_payload["event_counts"]["detection"] == 1

        negative_payload = _run_replay(
            tmp_path,
            manifest_path=FIXTURE_PACK_MANIFEST,
            wake_word=wake_word,
            input_name=f"{wake_word}_negative.wav",
            expect="none",
        )
        assert negative_payload["mode"] == "detector"
        assert negative_payload["wake_word"] == wake_word
        assert negative_payload["detection"] == "none"
        assert negative_payload["detection_count"] == 0
        assert negative_payload["detected_labels"] == []
        assert negative_payload["event_counts"].get("detection", 0) == 0


def test_runtime_hides_unvalidated_pack_entries() -> None:
    service = _build_service(UNVALIDATED_PACK_MANIFEST)

    assert service.registry.list_wake_words() == (
        "okay_nabu",
        "hey_jarvis",
        "hey_mycroft",
        "hey_rhasspy",
    )
    assert [wake_word.name for wake_word in service.server.describe().wake_words] == [
        "okay_nabu",
        "hey_jarvis",
        "hey_mycroft",
        "hey_rhasspy",
    ]
    inventory = {
        record.wake_word: record.as_report_dict() for record in service.inventory
    }
    assert inventory["alexa"]["evaluation_status"] == "pending"
    assert inventory["alexa"]["release_approved"] is True
    assert inventory["alexa"]["advertised"] is False
