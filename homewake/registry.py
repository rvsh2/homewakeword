"""Model manifest records and registry placeholders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Metadata required to identify and load a wake word model."""

    model_id: str
    wake_word: str
    version: str
    model_path: Path
    sample_rate_hz: int
    framework: str = "onnx"


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    """Container for resolved model manifests."""

    default_model: ModelManifest

    def resolve(self, backend: str) -> ModelManifest:
        """Return the manifest for a backend.

        The architecture currently supports one resolved manifest while the runtime
        contracts are being frozen.
        """

        if backend != "bcresnet":
            message = f"Unsupported detector backend: {backend}"
            raise LookupError(message)
        return self.default_model
