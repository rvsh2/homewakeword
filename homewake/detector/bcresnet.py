"""BC-ResNet detector adapter shell behind the neutral detector contract."""

from __future__ import annotations

from dataclasses import dataclass

from homewake.audio import AudioChunk
from homewake.config import DetectorConfig
from homewake.detector.base import DetectionDecision, DetectorRuntimeState
from homewake.registry import ModelManifest


@dataclass(slots=True)
class BCResNetDetector:
    """Placeholder BC-ResNet runtime adapter.

    This class intentionally exposes only the generic detector contract required by
    the rest of the package. Real model loading and inference arrive in later tasks.
    """

    config: DetectorConfig
    manifest: ModelManifest
    _is_open: bool = False

    @property
    def backend_name(self) -> str:
        return "bcresnet"

    def open(self) -> None:
        self._is_open = True

    def close(self) -> None:
        self._is_open = False

    def reset(self) -> None:
        """Reset placeholder state for future streaming implementations."""

    def process(self, chunk: AudioChunk) -> DetectionDecision:
        """Return a deterministic non-detection placeholder decision."""

        del chunk
        return DetectionDecision(
            detected=False,
            score=0.0,
            threshold=self.config.threshold,
            label=self.manifest.wake_word,
            state=DetectorRuntimeState(),
        )
