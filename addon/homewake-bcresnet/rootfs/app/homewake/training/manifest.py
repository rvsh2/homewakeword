"""Config parsing and manifest construction for offline custom training."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from homewake.audio import AudioFormatError, iter_wave_chunks
from homewake.config import AudioInputConfig, LogMelFrontendConfig
from homewake.registry import (
    ArtifactProvenance,
    EvaluationStatus,
    ModelManifest,
    ProvenanceStatus,
)


class TrainingValidationError(ValueError):
    """Raised when a custom training config or dataset is invalid."""


_FROZEN_AUDIO = AudioInputConfig()
_FROZEN_FRONTEND = LogMelFrontendConfig()


@dataclass(frozen=True, slots=True)
class DatasetConfig:
    train_positive_paths: tuple[Path, ...]
    holdout_positive: Path
    holdout_negative: Path


@dataclass(frozen=True, slots=True)
class ProvenanceConfig:
    source: str
    training_recipe: str
    training_recipe_version: str
    license: str


@dataclass(frozen=True, slots=True)
class ExportConfig:
    artifact_name: str


@dataclass(frozen=True, slots=True)
class DatasetSummary:
    train_positive_count: int
    train_positive_chunks: int
    holdout_positive_chunks: int
    holdout_negative_chunks: int


@dataclass(frozen=True, slots=True)
class CustomTrainingConfig:
    config_path: Path
    model_id: str
    wake_word: str
    version: str
    threshold: float
    dataset: DatasetConfig
    provenance: ProvenanceConfig
    export: ExportConfig
    audio: AudioInputConfig
    frontend: LogMelFrontendConfig


def _as_mapping(data: Any, *, context: str) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TrainingValidationError(f"{context} must be a mapping")
    return data


def _require_string(data: dict[str, Any], key: str, *, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise TrainingValidationError(
            f"{context} field '{key}' must be a non-empty string"
        )
    return value.strip()


def _resolve_path(raw_path: str, *, config_path: Path, field_name: str) -> Path:
    if not raw_path.strip():
        raise TrainingValidationError(
            f"config field '{field_name}' must be a non-empty string"
        )
    path = Path(raw_path)
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()
    return path


def _parse_audio(raw: dict[str, Any]) -> AudioInputConfig:
    audio = AudioInputConfig(
        sample_rate_hz=int(raw.get("sample_rate_hz", _FROZEN_AUDIO.sample_rate_hz)),
        sample_width_bytes=int(
            raw.get("sample_width_bytes", _FROZEN_AUDIO.sample_width_bytes)
        ),
        channels=int(raw.get("channels", _FROZEN_AUDIO.channels)),
        frame_samples=int(raw.get("frame_samples", _FROZEN_AUDIO.frame_samples)),
        window_seconds=float(raw.get("window_seconds", _FROZEN_AUDIO.window_seconds)),
    )
    if audio != _FROZEN_AUDIO:
        raise TrainingValidationError(
            "custom training only supports the frozen BC-ResNet audio contract: "
            "16 kHz mono PCM16, 1280-sample frames, 1.0-second context"
        )
    return audio


def _parse_frontend(raw: dict[str, Any]) -> LogMelFrontendConfig:
    frontend = LogMelFrontendConfig(
        n_fft=int(raw.get("n_fft", _FROZEN_FRONTEND.n_fft)),
        win_length=int(raw.get("win_length", _FROZEN_FRONTEND.win_length)),
        hop_length=int(raw.get("hop_length", _FROZEN_FRONTEND.hop_length)),
        n_mels=int(raw.get("n_mels", _FROZEN_FRONTEND.n_mels)),
        f_min_hz=float(raw.get("f_min_hz", _FROZEN_FRONTEND.f_min_hz)),
        f_max_hz=float(raw.get("f_max_hz", _FROZEN_FRONTEND.f_max_hz)),
        log_floor=float(raw.get("log_floor", _FROZEN_FRONTEND.log_floor)),
        context_seconds=float(
            raw.get("context_seconds", _FROZEN_FRONTEND.context_seconds)
        ),
    )
    if frontend != _FROZEN_FRONTEND:
        raise TrainingValidationError(
            "custom training only supports the frozen BC-ResNet frontend contract already used in this repo"
        )
    return frontend


def load_training_config(path: Path) -> CustomTrainingConfig:
    config_path = path.resolve()
    if not config_path.exists():
        raise TrainingValidationError(f"training config does not exist: {config_path}")
    if config_path.is_dir():
        raise TrainingValidationError(f"training config must be a file: {config_path}")

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise TrainingValidationError(f"malformed training config YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise TrainingValidationError("training config root must be a mapping")

    dataset_raw = _as_mapping(raw.get("dataset"), context="config.dataset")
    provenance_raw = _as_mapping(raw.get("provenance"), context="config.provenance")
    export_raw = _as_mapping(raw.get("export"), context="config.export")

    train_paths_raw = dataset_raw.get("train_positive_paths")
    if not isinstance(train_paths_raw, list) or not train_paths_raw:
        raise TrainingValidationError(
            "config.dataset field 'train_positive_paths' must be a non-empty list"
        )
    train_positive_paths = tuple(
        _resolve_path(
            str(item),
            config_path=config_path,
            field_name="dataset.train_positive_paths[]",
        )
        for item in train_paths_raw
        if isinstance(item, str)
    )
    if len(train_positive_paths) != len(train_paths_raw):
        raise TrainingValidationError(
            "config.dataset field 'train_positive_paths' must contain only strings"
        )

    threshold = float(raw.get("threshold", 0.55))
    if threshold <= 0.0 or threshold > 1.0:
        raise TrainingValidationError(
            "config field 'threshold' must be in the range (0.0, 1.0]"
        )

    artifact_name = export_raw.get(
        "artifact_name", f"{_require_string(raw, 'model_id', context='config')}.tflite"
    )
    if not isinstance(artifact_name, str) or not artifact_name.strip():
        raise TrainingValidationError(
            "config.export field 'artifact_name' must be a non-empty string"
        )
    if not artifact_name.endswith(".tflite"):
        raise TrainingValidationError(
            "config.export field 'artifact_name' must end with '.tflite'"
        )

    return CustomTrainingConfig(
        config_path=config_path,
        model_id=_require_string(raw, "model_id", context="config"),
        wake_word=_require_string(raw, "wake_word", context="config"),
        version=_require_string(raw, "version", context="config"),
        threshold=threshold,
        dataset=DatasetConfig(
            train_positive_paths=train_positive_paths,
            holdout_positive=_resolve_path(
                _require_string(
                    dataset_raw, "holdout_positive", context="config.dataset"
                ),
                config_path=config_path,
                field_name="dataset.holdout_positive",
            ),
            holdout_negative=_resolve_path(
                _require_string(
                    dataset_raw, "holdout_negative", context="config.dataset"
                ),
                config_path=config_path,
                field_name="dataset.holdout_negative",
            ),
        ),
        provenance=ProvenanceConfig(
            source=_require_string(
                provenance_raw, "source", context="config.provenance"
            ),
            training_recipe=_require_string(
                provenance_raw,
                "training_recipe",
                context="config.provenance",
            ),
            training_recipe_version=_require_string(
                provenance_raw,
                "training_recipe_version",
                context="config.provenance",
            ),
            license=_require_string(
                provenance_raw, "license", context="config.provenance"
            ),
        ),
        export=ExportConfig(artifact_name=artifact_name.strip()),
        audio=_parse_audio(_as_mapping(raw.get("audio"), context="config.audio")),
        frontend=_parse_frontend(
            _as_mapping(raw.get("frontend"), context="config.frontend")
        ),
    )


def _validate_wav(path: Path, audio: AudioInputConfig, *, role: str) -> int:
    if not path.exists():
        raise TrainingValidationError(f"{role} WAV does not exist: {path}")
    if path.is_dir():
        raise TrainingValidationError(f"{role} WAV must be a file: {path}")
    if path.suffix.lower() != ".wav":
        raise TrainingValidationError(f"{role} must be a .wav file: {path}")
    try:
        return len(iter_wave_chunks(path, audio))
    except AudioFormatError as exc:
        raise TrainingValidationError(f"{role} failed audio validation: {exc}") from exc


def validate_training_dataset(config: CustomTrainingConfig) -> DatasetSummary:
    train_positive_chunks = 0
    for path in config.dataset.train_positive_paths:
        train_positive_chunks += _validate_wav(
            path,
            config.audio,
            role="training positive",
        )

    holdout_positive_chunks = _validate_wav(
        config.dataset.holdout_positive,
        config.audio,
        role="holdout positive",
    )
    holdout_negative_chunks = _validate_wav(
        config.dataset.holdout_negative,
        config.audio,
        role="holdout negative",
    )
    return DatasetSummary(
        train_positive_count=len(config.dataset.train_positive_paths),
        train_positive_chunks=train_positive_chunks,
        holdout_positive_chunks=holdout_positive_chunks,
        holdout_negative_chunks=holdout_negative_chunks,
    )


def build_runtime_manifest(
    config: CustomTrainingConfig,
    *,
    artifact_path: Path,
    artifact_sha256: str,
) -> ModelManifest:
    return ModelManifest(
        model_id=config.model_id,
        wake_word=config.wake_word,
        version=config.version,
        model_path=artifact_path.resolve(),
        sample_rate_hz=config.audio.sample_rate_hz,
        framework="tflite",
        backend="bcresnet",
        threshold=config.threshold,
        audio=config.audio,
        frontend=config.frontend,
        provenance=ArtifactProvenance(
            source=config.provenance.source,
            training_recipe=config.provenance.training_recipe,
            training_recipe_version=config.provenance.training_recipe_version,
            artifact_sha256=artifact_sha256,
            license=config.provenance.license,
            provenance_status=ProvenanceStatus.UNVERIFIABLE,
        ),
        evaluation=None,
        manifest_path=(artifact_path.parent / "manifest.yaml").resolve(),
    )


def build_training_manifest_mapping(
    config: CustomTrainingConfig,
    *,
    artifact_name: str,
    artifact_sha256: str,
    evaluation_status: EvaluationStatus,
    positive_fixture_path: Path,
    negative_fixture_path: Path,
) -> dict[str, object]:
    return {
        "model_id": config.model_id,
        "wake_word": config.wake_word,
        "version": config.version,
        "backend": "bcresnet",
        "framework": "tflite",
        "model_path": artifact_name,
        "threshold": config.threshold,
        "provenance": {
            "source": config.provenance.source,
            "training_recipe": config.provenance.training_recipe,
            "training_recipe_version": config.provenance.training_recipe_version,
            "artifact_sha256": artifact_sha256,
            "license": config.provenance.license,
            "provenance_status": ProvenanceStatus.UNVERIFIABLE.value,
        },
        "evaluation": {
            "status": evaluation_status.value,
            "positive_fixture": str(positive_fixture_path),
            "negative_fixture": str(negative_fixture_path),
        },
        "audio": {
            "sample_rate_hz": config.audio.sample_rate_hz,
            "sample_width_bytes": config.audio.sample_width_bytes,
            "channels": config.audio.channels,
            "frame_samples": config.audio.frame_samples,
            "window_seconds": config.audio.window_seconds,
        },
        "frontend": {
            "n_fft": config.frontend.n_fft,
            "win_length": config.frontend.win_length,
            "hop_length": config.frontend.hop_length,
            "n_mels": config.frontend.n_mels,
            "f_min_hz": config.frontend.f_min_hz,
            "f_max_hz": config.frontend.f_max_hz,
            "log_floor": config.frontend.log_floor,
            "context_seconds": config.frontend.context_seconds,
        },
    }
