"""Model manifest schema, loading helpers, and registry resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any

import yaml

from homewake.config import AudioInputConfig, DetectorConfig, LogMelFrontendConfig

SUPPORTED_BACKEND = "bcresnet"
DEFAULT_FRAMEWORK = "tflite"
ONNX_ENV_FLAG = "HOMEWAKE_ENABLE_ONNX"
_FRAMEWORK_SUFFIXES = {
    "tflite": ".tflite",
    "onnx": ".onnx",
}


class ManifestValidationError(ValueError):
    """Raised when a model manifest is missing required data or is invalid."""


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Metadata required to identify and load a wake word model."""

    model_id: str
    wake_word: str
    version: str
    model_path: Path | None
    sample_rate_hz: int
    framework: str = DEFAULT_FRAMEWORK
    backend: str = SUPPORTED_BACKEND
    threshold: float = 1.0
    audio: AudioInputConfig = field(default_factory=AudioInputConfig)
    frontend: LogMelFrontendConfig = field(default_factory=LogMelFrontendConfig)
    manifest_path: Path | None = None

    @property
    def mode(self) -> str:
        return "detector" if self.model_path is not None else "frontend_only"

    @property
    def expects_artifact(self) -> bool:
        return self.model_path is not None

    def detector_config(self) -> DetectorConfig:
        return DetectorConfig(
            backend=self.backend,
            threshold=self.threshold,
            manifest_path=self.manifest_path,
            frontend=self.frontend,
        )


def _as_mapping(data: Any, *, context: str) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ManifestValidationError(f"{context} must be a mapping")
    return data


def _require_string(
    data: dict[str, Any], key: str, *, default: str | None = None
) -> str:
    value = data.get(key, default)
    if value is None or not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(
            f"manifest field '{key}' must be a non-empty string"
        )
    return value.strip()


def _coerce_framework(value: str | None) -> str:
    framework = (value or DEFAULT_FRAMEWORK).strip().lower()
    if framework not in _FRAMEWORK_SUFFIXES:
        raise ManifestValidationError(
            f"unsupported framework '{framework}'; supported values are: {', '.join(sorted(_FRAMEWORK_SUFFIXES))}"
        )
    if framework == "onnx" and os.getenv(ONNX_ENV_FLAG) != "1":
        raise ManifestValidationError(
            f"framework 'onnx' requires explicit opt-in via {ONNX_ENV_FLAG}=1"
        )
    return framework


def _resolve_model_path(raw_path: str | None, manifest_path: Path) -> Path | None:
    if raw_path is None:
        return None
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ManifestValidationError(
            "manifest field 'model_path' must be a non-empty string when provided"
        )
    model_path = Path(raw_path)
    if not model_path.is_absolute():
        model_path = (manifest_path.parent / model_path).resolve()
    return model_path


def validate_manifest(
    manifest: ModelManifest, *, require_artifact: bool = True
) -> ModelManifest:
    if manifest.backend != SUPPORTED_BACKEND:
        raise ManifestValidationError(
            f"unsupported detector backend: expected '{SUPPORTED_BACKEND}', got '{manifest.backend}'"
        )
    if manifest.sample_rate_hz != manifest.audio.sample_rate_hz:
        raise ManifestValidationError(
            "manifest sample_rate_hz must match audio.sample_rate_hz"
        )
    if require_artifact and manifest.model_path is None:
        raise ManifestValidationError("detector manifests must define 'model_path'")
    if manifest.model_path is not None:
        suffix = _FRAMEWORK_SUFFIXES[manifest.framework]
        if manifest.model_path.suffix.lower() != suffix:
            raise ManifestValidationError(
                f"framework '{manifest.framework}' expects artifact suffix '{suffix}', got '{manifest.model_path.suffix or '<none>'}'"
            )
        if require_artifact and not manifest.model_path.exists():
            raise ManifestValidationError(
                f"model artifact does not exist: {manifest.model_path}"
            )
    return manifest


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    """Container for resolved model manifests."""

    default_model: ModelManifest

    def list_wake_words(self) -> tuple[str, ...]:
        """Return wake words from the manifest-backed registry source of truth."""

        return (self.default_model.wake_word,)

    def resolve(self, backend: str, *, framework: str | None = None) -> ModelManifest:
        """Return the manifest for a backend and optional framework."""

        manifest = self.default_model
        if backend != manifest.backend:
            raise LookupError(f"Unsupported detector backend: {backend}")
        if framework is not None and framework.lower() != manifest.framework:
            raise LookupError(
                f"Unsupported framework '{framework}' for backend '{backend}'"
            )
        return manifest


def load_manifest(path: Path, *, require_artifact: bool = True) -> ModelManifest:
    """Load and validate one BC-ResNet manifest from YAML."""

    manifest_path = path.resolve()
    if not manifest_path.exists():
        raise ManifestValidationError(f"manifest file does not exist: {manifest_path}")
    if manifest_path.is_dir():
        raise ManifestValidationError(f"manifest path must be a file: {manifest_path}")

    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ManifestValidationError(f"malformed manifest YAML: {exc}") from exc

    root = _as_mapping(raw, context="manifest")
    audio_data = _as_mapping(root.get("audio"), context="manifest.audio")
    frontend_data = _as_mapping(root.get("frontend"), context="manifest.frontend")

    sample_rate_hz = int(
        audio_data.get("sample_rate_hz", root.get("sample_rate_hz", 16_000))
    )
    audio = AudioInputConfig(
        sample_rate_hz=sample_rate_hz,
        sample_width_bytes=int(audio_data.get("sample_width_bytes", 2)),
        channels=int(audio_data.get("channels", 1)),
        frame_samples=int(audio_data.get("frame_samples", 1_280)),
        window_seconds=float(audio_data.get("window_seconds", 1.0)),
    )
    frontend = LogMelFrontendConfig(
        n_fft=int(frontend_data.get("n_fft", 512)),
        win_length=int(frontend_data.get("win_length", 480)),
        hop_length=int(frontend_data.get("hop_length", 160)),
        n_mels=int(frontend_data.get("n_mels", 40)),
        f_min_hz=float(frontend_data.get("f_min_hz", 20.0)),
        f_max_hz=float(frontend_data.get("f_max_hz", 7_600.0)),
        log_floor=float(frontend_data.get("log_floor", 1e-6)),
        context_seconds=float(frontend_data.get("context_seconds", 1.0)),
    )

    raw_model_path = root.get("model_path")
    if raw_model_path is None and not require_artifact:
        framework = DEFAULT_FRAMEWORK
        backend = SUPPORTED_BACKEND
    else:
        framework = _coerce_framework(root.get("framework"))
        backend = _require_string(root, "backend", default=SUPPORTED_BACKEND).lower()

    manifest = ModelManifest(
        model_id=_require_string(root, "model_id", default="frontend_only"),
        wake_word=_require_string(root, "wake_word", default="frontend_only"),
        version=_require_string(root, "version", default="0.0.0"),
        model_path=_resolve_model_path(raw_model_path, manifest_path),
        sample_rate_hz=sample_rate_hz,
        framework=framework,
        backend=backend,
        threshold=float(root.get("threshold", 1.0)),
        audio=audio,
        frontend=frontend,
        manifest_path=manifest_path,
    )
    return validate_manifest(manifest, require_artifact=require_artifact)


def load_registry(path: Path, *, require_artifact: bool = True) -> ModelRegistry:
    """Load the current single-model registry from a manifest file."""

    return ModelRegistry(
        default_model=load_manifest(path, require_artifact=require_artifact)
    )
