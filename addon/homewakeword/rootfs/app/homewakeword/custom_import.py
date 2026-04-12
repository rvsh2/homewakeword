"""Filesystem import helpers for validated and auto-generated custom model bundles."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import yaml

from homewakeword.config import CustomModelImportConfig
from homewakeword.registry import (
    ManifestValidationError,
    ModelManifest,
    ModelRegistry,
    load_manifest,
)

_VERSION_SUFFIX_RE = re.compile(r"^(?P<name>.+?)_v(?P<version>[0-9.]+)$")
_AUTO_MANIFEST_SUFFIX = ".manifest.yaml"
_STANDALONE_MODEL_GLOBS = ("*.tflite",)


@dataclass(frozen=True, slots=True)
class CustomModelImportResult:
    """Structured result for filesystem-backed custom model imports."""

    manifests: tuple[ModelManifest, ...] = ()
    scanned_directories: tuple[Path, ...] = ()
    loaded_manifest_paths: tuple[Path, ...] = ()
    generated_manifest_paths: tuple[Path, ...] = ()
    rejected: tuple[str, ...] = ()

    @property
    def imported_wake_words(self) -> tuple[str, ...]:
        return tuple(manifest.wake_word for manifest in self.manifests)


def _manifest_paths(root: Path) -> tuple[Path, ...]:
    if not root.exists() or not root.is_dir():
        return ()
    manifests = {
        *root.rglob("manifest.yaml"),
        *root.rglob(f"*{_AUTO_MANIFEST_SUFFIX}"),
    }
    return tuple(sorted(path.resolve() for path in manifests))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65_536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar_manifest_path(artifact_path: Path) -> Path:
    return artifact_path.with_suffix(_AUTO_MANIFEST_SUFFIX)


def _infer_names(stem: str) -> tuple[str, str, str]:
    normalized = stem.strip().lower()
    match = _VERSION_SUFFIX_RE.fullmatch(normalized)
    if match is None:
        wake_word = normalized
        version = "0.0.0"
        model_id = f"{wake_word}_auto"
        return wake_word, version, model_id
    wake_word = match.group("name")
    version = match.group("version")
    model_id = normalized
    return wake_word, version, model_id


def _write_auto_manifest(artifact_path: Path) -> Path:
    wake_word, version, model_id = _infer_names(artifact_path.stem)
    manifest_path = _sidecar_manifest_path(artifact_path)
    payload = {
        "model_id": model_id,
        "wake_word": wake_word,
        "version": version,
        "backend": "bcresnet",
        "framework": "tflite",
        "model_path": artifact_path.name,
        "threshold": 0.55,
        "provenance": {
            "source": f"auto-import://{artifact_path.name}",
            "training_recipe": "homewakeword-auto-import",
            "training_recipe_version": "1.0.0",
            "artifact_sha256": _sha256_file(artifact_path),
            "license": "LicenseRef-HomeWakeWord-Auto-Imported",
            "provenance_status": "unverifiable",
        },
        "audio": {
            "sample_rate_hz": 16000,
            "sample_width_bytes": 2,
            "channels": 1,
            "frame_samples": 1280,
            "window_seconds": 1.0,
        },
        "frontend": {
            "n_fft": 512,
            "win_length": 480,
            "hop_length": 160,
            "n_mels": 40,
            "f_min_hz": 20.0,
            "f_max_hz": 7600.0,
            "log_floor": 1.0e-6,
            "context_seconds": 1.0,
        },
    }
    manifest_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return manifest_path.resolve()


def _materialize_auto_manifests(root: Path, *, rejected: list[str]) -> tuple[Path, ...]:
    if not root.exists() or not root.is_dir():
        return ()

    generated: list[Path] = []
    for pattern in _STANDALONE_MODEL_GLOBS:
        for artifact_path in sorted(root.rglob(pattern)):
            sibling_manifest = artifact_path.parent / "manifest.yaml"
            sidecar_manifest = _sidecar_manifest_path(artifact_path)
            if sibling_manifest.exists() or sidecar_manifest.exists():
                continue
            try:
                generated.append(_write_auto_manifest(artifact_path))
            except OSError as exc:
                rejected.append(
                    f"failed to generate auto manifest for custom model {artifact_path.resolve()}: {exc}"
                )
    return tuple(generated)


def _import_roots(config: CustomModelImportConfig) -> tuple[Path, ...]:
    roots: list[Path] = []
    if config.enabled:
        roots.append(config.directory.resolve())
    if config.openwakeword_compat_enabled:
        roots.append(config.openwakeword_directory.resolve())
    return tuple(roots)


def import_custom_model_bundles(
    config: CustomModelImportConfig,
    *,
    base_registry: ModelRegistry,
) -> CustomModelImportResult:
    """Load valid custom bundles from configured directories without protocol coupling."""

    roots = _import_roots(config)
    if not roots:
        return CustomModelImportResult()

    rejected: list[str] = []
    manifests: list[ModelManifest] = []
    loaded_manifest_paths: list[Path] = []
    generated_manifest_paths: list[Path] = []
    seen_model_ids = {manifest.model_id for manifest in base_registry.models}
    seen_wake_words = {manifest.wake_word for manifest in base_registry.models}

    for root in roots:
        if root.exists() and not root.is_dir():
            rejected.append(f"custom model import root must be a directory: {root}")
            continue

        generated_manifest_paths.extend(
            _materialize_auto_manifests(root, rejected=rejected)
        )
        for manifest_path in _manifest_paths(root):
            try:
                manifest = load_manifest(manifest_path, require_artifact=True)
            except (ManifestValidationError, OSError) as exc:
                rejected.append(f"rejected custom manifest {manifest_path}: {exc}")
                continue

            inventory = manifest.inventory_record(verify_hash=True)
            if not inventory.runtime_approved:
                rejected.append(
                    "rejected custom manifest "
                    f"{manifest_path}: runtime approval failed for model '{manifest.model_id}'"
                )
                continue
            if not inventory.evaluation_validated:
                rejected.append(
                    "rejected custom manifest "
                    f"{manifest_path}: evaluation status must be validated for advertised imports"
                )
                continue
            if manifest.model_id in seen_model_ids:
                rejected.append(
                    f"rejected custom manifest {manifest_path}: duplicate model_id '{manifest.model_id}'"
                )
                continue
            if manifest.wake_word in seen_wake_words:
                rejected.append(
                    f"rejected custom manifest {manifest_path}: duplicate wake_word '{manifest.wake_word}'"
                )
                continue

            seen_model_ids.add(manifest.model_id)
            seen_wake_words.add(manifest.wake_word)
            manifests.append(manifest)
            loaded_manifest_paths.append(manifest_path.resolve())

    return CustomModelImportResult(
        manifests=tuple(manifests),
        scanned_directories=roots,
        loaded_manifest_paths=tuple(loaded_manifest_paths),
        generated_manifest_paths=tuple(generated_manifest_paths),
        rejected=tuple(rejected),
    )
