from __future__ import annotations

import ast
from pathlib import Path
from typing import get_type_hints

from homewake.audio import AudioChunk
from homewake.config import HomeWakeConfig
from homewake.detector.base import (
    DetectionDecision,
    DetectorRuntimeState,
    WakeWordDetector,
)
from homewake.events import DetectionEventType
from homewake.server.wyoming import WyomingRuntime, WyomingServer


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WYOMING_MODULE = PROJECT_ROOT / "homewake" / "server" / "wyoming.py"


class FakeDetector:
    @property
    def backend_name(self) -> str:
        return "fake"

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def reset(self) -> None:
        return None

    def process(self, chunk: AudioChunk) -> DetectionDecision:
        del chunk
        return DetectionDecision(
            detected=False,
            score=0.1,
            threshold=0.5,
            label="hey_homewake",
            state=DetectorRuntimeState(
                cooldown_remaining_seconds=0.0, refractory_remaining_seconds=0.0
            ),
        )


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_wyoming_server_imports_only_contract_layers() -> None:
    imports = _imported_modules(WYOMING_MODULE)

    assert "homewake.detector.base" in imports
    assert "homewake.events" in imports
    assert "homewake.detector.bcresnet" not in imports


def test_wyoming_runtime_is_typed_against_detector_protocol() -> None:
    hints = get_type_hints(WyomingRuntime)

    assert hints["detector"] is WakeWordDetector


def test_wyoming_runtime_emits_structured_events() -> None:
    runtime = WyomingRuntime(config=HomeWakeConfig(), detector=FakeDetector())
    event = runtime.handle_audio_chunk(
        AudioChunk(pcm=b"\x00\x00" * 160, sample_rate_hz=16_000, sample_width_bytes=2)
    )

    assert event.type is DetectionEventType.SCORED
    assert event.detector_backend == "fake"
    assert event.decision.label == "hey_homewake"


def test_wyoming_server_uses_runtime_config_boundary() -> None:
    runtime = WyomingRuntime(config=HomeWakeConfig(), detector=FakeDetector())
    server = WyomingServer.from_runtime(runtime)

    assert server.config is runtime.config.server
