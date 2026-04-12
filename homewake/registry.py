"""Model manifest schema, loading helpers, and registry resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import os
from pathlib import Path
import re
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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ManifestValidationError(ValueError):
    """Raised when a model manifest is missing required data or is invalid."""


class ProvenanceStatus(StrEnum):
    """Review state for artifact provenance and bundling eligibility."""

    APPROVED = "approved"
    UNAPPROVED = "unapproved"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class ArtifactProvenance:
    """Explicit provenance metadata required for shipped detector artifacts."""

    source: str
    training_recipe: str
    training_recipe_version: str
    artifact_sha256: str
    license: str
    provenance_status: ProvenanceStatus


@dataclass(frozen=True, slots=True)
class ModelInventoryRecord:
    """Neutral runtime inventory view derived from manifest metadata."""

    model_id: str
    wake_word: str
    version: str
    backend: str
    framework: str
    threshold: float
    mode: str
    artifact_name: str | None
    artifact_size_bytes: int | None
    source: str | None
    training_recipe: str | None
    training_recipe_version: str | None
    license: str | None
    provenance_status: str | None
    expected_sha256: str | None
    actual_sha256: str | None
    hash_verified: bool | None

    @property
    def release_approved(self) -> bool:
        if self.mode != "detector":
            return True
        return (
            self.provenance_status == ProvenanceStatus.APPROVED.value
            and self.expected_sha256 is not None
            and self.hash_verified is True
        )

    def as_public_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "model_id": self.model_id,
            "wake_word": self.wake_word,
            "version": self.version,
            "backend": self.backend,
            "framework": self.framework,
            "threshold": self.threshold,
            "mode": self.mode,
            "provenance_status": self.provenance_status,
            "hash_verified": self.hash_verified,
        }
        if self.artifact_name is not None:
            payload["artifact"] = self.artifact_name
        if self.license is not None:
            payload["license"] = self.license
        return payload

    def as_report_dict(self) -> dict[str, object]:
        payload = self.as_public_dict()
        payload.update(
            {
                "artifact_size_bytes": self.artifact_size_bytes,
                "source": self.source,
                "training_recipe": self.training_recipe,
                "training_recipe_version": self.training_recipe_version,
                "expected_sha256": self.expected_sha256,
                "actual_sha256": self.actual_sha256,
                "release_approved": self.release_approved,
            }
        )
        return payload


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
    provenance: ArtifactProvenance | None = None
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

    def inventory_record(self, *, verify_hash: bool = False) -> ModelInventoryRecord:
        artifact_name = None if self.model_path is None else self.model_path.name
        artifact_size_bytes = None
        actual_sha256 = None
        hash_verified = None
        if self.model_path is not None and self.model_path.exists():
            artifact_size_bytes = self.model_path.stat().st_size
            if verify_hash and self.provenance is not None:
                actual_sha256 = _sha256_file(self.model_path)
                hash_verified = actual_sha256 == self.provenance.artifact_sha256
        elif self.model_path is not None and verify_hash:
            hash_verified = False

        return ModelInventoryRecord(
            model_id=self.model_id,
            wake_word=self.wake_word,
            version=self.version,
            backend=self.backend,
            framework=self.framework,
            threshold=self.threshold,
            mode=self.mode,
            artifact_name=artifact_name,
            artifact_size_bytes=artifact_size_bytes,
            source=None if self.provenance is None else self.provenance.source,
            training_recipe=None
            if self.provenance is None
            else self.provenance.training_recipe,
            training_recipe_version=None
            if self.provenance is None
            else self.provenance.training_recipe_version,
            license=None if self.provenance is None else self.provenance.license,
            provenance_status=None
            if self.provenance is None
            else self.provenance.provenance_status.value,
            expected_sha256=None
            if self.provenance is None
            else self.provenance.artifact_sha256,
            actual_sha256=actual_sha256,
            hash_verified=hash_verified,
        )


def _as_mapping(data: Any, *, context: str) -> dict[str, Any]:
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ManifestValidationError(f"{context} must be a mapping")
    return data


def _require_string(
    data: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
    context: str = "manifest",
) -> str:
    value = data.get(key, default)
    if value is None or not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(
            f"{context} field '{key}' must be a non-empty string"
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


def _coerce_provenance_status(value: str | None) -> ProvenanceStatus:
    normalized = (value or "").strip().lower()
    try:
        return ProvenanceStatus(normalized)
    except ValueError as exc:
        raise ManifestValidationError(
            "manifest.provenance field 'provenance_status' must be one of: "
            + ", ".join(status.value for status in ProvenanceStatus)
        ) from exc


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


def _parse_provenance(
    data: Any, *, artifact_required: bool
) -> ArtifactProvenance | None:
    if data is None:
        if artifact_required:
            raise ManifestValidationError(
                "detector manifests must define a provenance mapping"
            )
        return None

    provenance_data = _as_mapping(data, context="manifest.provenance")
    artifact_sha256 = _require_string(
        provenance_data,
        "artifact_sha256",
        context="manifest.provenance",
    )
    if _SHA256_RE.fullmatch(artifact_sha256) is None:
        raise ManifestValidationError(
            "manifest.provenance field 'artifact_sha256' must be a 64-character lowercase hex SHA-256"
        )

    return ArtifactProvenance(
        source=_require_string(
            provenance_data,
            "source",
            context="manifest.provenance",
        ),
        training_recipe=_require_string(
            provenance_data,
            "training_recipe",
            context="manifest.provenance",
        ),
        training_recipe_version=_require_string(
            provenance_data,
            "training_recipe_version",
            context="manifest.provenance",
        ),
        artifact_sha256=artifact_sha256,
        license=_require_string(
            provenance_data,
            "license",
            context="manifest.provenance",
        ),
        provenance_status=_coerce_provenance_status(
            provenance_data.get("provenance_status")
        ),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65_536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


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
        if manifest.provenance is None:
            raise ManifestValidationError(
                "detector manifests must define explicit provenance metadata"
            )
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


def validate_release_manifest(path: Path) -> ModelInventoryRecord:
    """Load a shipped detector manifest and enforce provenance/hash release gates."""

    manifest = load_manifest(path, require_artifact=True)
    inventory = manifest.inventory_record(verify_hash=True)
    if inventory.provenance_status != ProvenanceStatus.APPROVED.value:
        raise ManifestValidationError(
            "release manifest requires provenance_status=approved; "
            f"got {inventory.provenance_status!r} for model '{inventory.model_id}'"
        )
    if inventory.hash_verified is not True:
        raise ManifestValidationError(
            "release manifest hash verification failed for model "
            f"'{inventory.model_id}'"
        )
    return inventory


@dataclass(frozen=True, slots=True)
class ModelRegistry:
    """Container for resolved model manifests."""

    default_model: ModelManifest

    def list_wake_words(self) -> tuple[str, ...]:
        """Return wake words from the manifest-backed registry source of truth."""

        return (self.default_model.wake_word,)

    def inventory(
        self, *, verify_hash: bool = False
    ) -> tuple[ModelInventoryRecord, ...]:
        """Return loaded-model inventory derived from manifest metadata."""

        return (self.default_model.inventory_record(verify_hash=verify_hash),)

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
        provenance=_parse_provenance(
            root.get("provenance"),
            artifact_required=raw_model_path is not None,
        ),
        manifest_path=manifest_path,
    )
    return validate_manifest(manifest, require_artifact=require_artifact)


def load_registry(path: Path, *, require_artifact: bool = True) -> ModelRegistry:
    """Load the current single-model registry from a manifest file."""

    return ModelRegistry(
        default_model=load_manifest(path, require_artifact=require_artifact)
    )
