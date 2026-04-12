"""Filesystem import helpers for validated custom model bundles."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homewake.config import CustomModelImportConfig
from homewake.registry import ManifestValidationError, ModelManifest, ModelRegistry, load_manifest


@dataclass(frozen=True, slots=True)
class CustomModelImportResult:
    """Structured result for filesystem-backed custom model imports."""

    manifests: tuple[ModelManifest, ...] = ()
    scanned_directories: tuple[Path, ...] = ()
    loaded_manifest_paths: tuple[Path, ...] = ()
    rejected: tuple[str, ...] = ()

    @property
    def imported_wake_words(self) -> tuple[str, ...]:
        return tuple(manifest.wake_word for manifest in self.manifests)


def _manifest_paths(root: Path) -> tuple[Path, ...]:
    if not root.exists() or not root.is_dir():
        return ()
    return tuple(sorted(path.resolve() for path in root.rglob("manifest.yaml")))


def _reject_manifestless_artifacts(root: Path, *, rejected: list[str]) -> None:
    if not root.exists() or not root.is_dir():
        return
    for suffix in ("*.tflite", "*.onnx"):
        for artifact_path in sorted(root.rglob(suffix)):
            sibling_manifest = artifact_path.parent / "manifest.yaml"
            if sibling_manifest.exists():
                continue
            rejected.append(
                "custom model artifact requires sibling manifest.yaml with provenance metadata: "
                f"{artifact_path.resolve()}"
            )


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
    seen_model_ids = {manifest.model_id for manifest in base_registry.models}
    seen_wake_words = {manifest.wake_word for manifest in base_registry.models}

    for root in roots:
        if root.exists() and not root.is_dir():
            rejected.append(f"custom model import root must be a directory: {root}")
            continue

        _reject_manifestless_artifacts(root, rejected=rejected)
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
            loaded_manifest_paths.append(manifest_path)

    return CustomModelImportResult(
        manifests=tuple(manifests),
        scanned_directories=roots,
        loaded_manifest_paths=tuple(loaded_manifest_paths),
        rejected=tuple(rejected),
    )
