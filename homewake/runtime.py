"""Package-level composition for HomeWake runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from homewake.config import DetectorConfig, HomeWakeConfig
from homewake.detector.bcresnet import BCResNetDetector
from homewake.registry import ModelManifest, ModelRegistry, load_registry
from homewake.server.wyoming import WyomingRuntime, WyomingServer


DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "models" / "manifest.yaml"


@dataclass(frozen=True, slots=True)
class HomeWakeService:
    """Composed runtime service with registry-backed protocol metadata."""

    config: HomeWakeConfig
    registry: ModelRegistry
    manifest: ModelManifest
    server: WyomingServer


def resolve_manifest_path(config: HomeWakeConfig) -> Path:
    """Resolve the manifest path used by runtime composition."""

    return (config.detector.manifest_path or DEFAULT_MANIFEST_PATH).resolve()


def build_service_config(
    config: HomeWakeConfig, manifest: ModelManifest
) -> HomeWakeConfig:
    """Merge manifest-backed detector defaults into runtime config."""

    return HomeWakeConfig(
        audio=manifest.audio,
        detector=DetectorConfig(
            backend=manifest.backend,
            threshold=manifest.threshold,
            manifest_path=manifest.manifest_path,
            cooldown=config.detector.cooldown,
            refractory=config.detector.refractory,
            frontend=manifest.frontend,
        ),
        server=config.server,
    )


def build_service(config: HomeWakeConfig) -> HomeWakeService:
    """Build a Wyoming-facing service from manifest-backed runtime inputs."""

    manifest_path = resolve_manifest_path(config)
    registry = load_registry(manifest_path, require_artifact=True)
    manifest = registry.resolve(config.detector.backend)
    service_config = build_service_config(config, manifest)
    detector = BCResNetDetector(
        config=service_config.detector,
        manifest=manifest,
        audio_config=service_config.audio,
    )
    runtime = WyomingRuntime(config=service_config, detector=detector)
    server = WyomingServer.from_runtime(
        runtime,
        loaded_wake_words=registry.list_wake_words(),
    )
    return HomeWakeService(
        config=service_config,
        registry=registry,
        manifest=manifest,
        server=server,
    )
