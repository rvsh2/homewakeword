"""Package-level composition for HomeWake runtime wiring."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
import resource
from pathlib import Path
from typing import Any

from homewake.config import DetectorConfig, HomeWakeConfig
from homewake.custom_import import CustomModelImportResult, import_custom_model_bundles
from homewake.detector.bcresnet import BCResNetDetector
from homewake.health import build_runtime_health
from homewake.registry import (
    ModelInventoryRecord,
    ModelManifest,
    ModelRegistry,
    load_registry,
    merge_registries,
)
from homewake.server.wyoming import WyomingRuntime, WyomingServer


DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "models" / "manifest.yaml"
_SENSITIVE_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "access_key",
    "client_secret",
)


@dataclass(frozen=True, slots=True)
class HomeWakeService:
    """Composed runtime service with registry-backed protocol metadata."""

    config: HomeWakeConfig
    registry: ModelRegistry
    manifest: ModelManifest
    inventory: tuple[ModelInventoryRecord, ...]
    custom_imports: CustomModelImportResult
    config_echo: dict[str, object]
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
        custom_models=config.custom_models,
        server=config.server,
    )


def _sanitize_value(value: Any, *, key: str | None = None) -> Any:
    normalized_key = "" if key is None else key.lower()
    if any(marker in normalized_key for marker in _SENSITIVE_KEY_MARKERS):
        return "<redacted>"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _sanitize_value(getattr(value, field.name), key=field.name)
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {
            str(nested_key): _sanitize_value(nested_value, key=str(nested_key))
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return value


def build_config_echo(config: HomeWakeConfig) -> dict[str, object]:
    """Render a compact config echo that is safe to expose in reports."""

    payload = _sanitize_value(config)
    if not isinstance(payload, dict):
        return {}
    return payload


def _read_proc_status_bytes(field_name: str) -> int | None:
    status_path = Path("/proc/self/status")
    if not status_path.exists():
        return None
    try:
        lines = status_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    prefix = f"{field_name}:"
    for line in lines:
        if not line.startswith(prefix):
            continue
        parts = line.split()
        if len(parts) < 2:
            return None
        try:
            return int(parts[1]) * 1024
        except ValueError:
            return None
    return None


def collect_process_resources() -> dict[str, object]:
    """Capture current process resource usage for reliability reporting."""

    usage = resource.getrusage(resource.RUSAGE_SELF)
    peak_rss_bytes = _read_proc_status_bytes("VmHWM")
    if peak_rss_bytes is None:
        peak_rss_bytes = int(usage.ru_maxrss) * 1024
    rss_bytes = _read_proc_status_bytes("VmRSS")
    if rss_bytes is None:
        rss_bytes = peak_rss_bytes
    return {
        "rss_bytes": rss_bytes,
        "peak_rss_bytes": peak_rss_bytes,
        "user_cpu_seconds": round(usage.ru_utime, 6),
        "system_cpu_seconds": round(usage.ru_stime, 6),
    }


def _classification_from_overall(overall: str) -> str:
    if overall == "ready":
        return "healthy"
    if overall == "degraded":
        return "degraded"
    return "unhealthy"


def collect_runtime_diagnostics(
    service: HomeWakeService,
    *,
    startup_duration_ms: float | None = None,
    notes: list[str] | None = None,
    startup_error: str | None = None,
) -> dict[str, object]:
    """Collect structured startup/runtime diagnostics without protocol coupling."""

    detector = service.server.runtime.detector
    diagnostics: dict[str, object] = {
        "service_uri": service.server.uri,
        "running": service.server.is_running,
        "manifest_path": str(resolve_manifest_path(service.config)),
        "loaded_model_count": len(service.inventory),
        "loaded_wake_words": list(service.registry.list_wake_words()),
        "mode": service.manifest.mode,
        "imported_model_count": len(service.custom_imports.manifests),
        "imported_wake_words": list(service.custom_imports.imported_wake_words),
        "imported_manifest_paths": [
            str(path) for path in service.custom_imports.loaded_manifest_paths
        ],
        "custom_import_rejections": list(service.custom_imports.rejected),
        "process_resources": collect_process_resources(),
    }
    if startup_duration_ms is not None:
        diagnostics["startup_duration_ms"] = round(startup_duration_ms, 3)
    if notes:
        diagnostics["notes"] = list(notes)
    if startup_error is not None:
        diagnostics["startup_error"] = startup_error
    runtime_handle = getattr(detector, "runtime", None)
    if runtime_handle is not None:
        diagnostics["artifact_size_bytes"] = runtime_handle.artifact_size_bytes
    counters = getattr(detector, "counters", None)
    if counters is not None:
        diagnostics["detector_counters"] = _sanitize_value(counters)
    return diagnostics


def build_runtime_report(
    service: HomeWakeService,
    *,
    startup_duration_ms: float | None = None,
    notes: list[str] | None = None,
) -> dict[str, object]:
    """Build a detailed runtime report for self-test and startup diagnostics."""

    payload = build_runtime_health(
        running=service.server.is_running,
        loaded_wake_words=service.registry.list_wake_words(),
        inventory=service.inventory,
        config=service.config_echo,
        diagnostics=collect_runtime_diagnostics(
            service,
            startup_duration_ms=startup_duration_ms,
            notes=notes,
        ),
    ).as_dict(include_details=True)
    payload["classification"] = _classification_from_overall(str(payload["overall"]))
    return payload


def build_startup_failure_report(
    config: HomeWakeConfig,
    *,
    error: BaseException | str,
    startup_duration_ms: float | None = None,
    notes: list[str] | None = None,
) -> dict[str, object]:
    """Build an explicit unhealthy report when startup or reload fails."""

    diagnostics: dict[str, object] = {
        "service_uri": f"tcp://{config.server.host}:{config.server.port}",
        "running": False,
        "manifest_path": str(resolve_manifest_path(config)),
        "loaded_model_count": 0,
        "loaded_wake_words": [],
        "mode": "startup_failed",
        "startup_error": str(error),
        "startup_error_type": (
            type(error).__name__ if isinstance(error, BaseException) else "RuntimeError"
        ),
        "process_resources": collect_process_resources(),
    }
    if startup_duration_ms is not None:
        diagnostics["startup_duration_ms"] = round(startup_duration_ms, 3)
    if notes:
        diagnostics["notes"] = list(notes)
    payload = build_runtime_health(
        running=False,
        loaded_wake_words=(),
        inventory=(),
        config=build_config_echo(config),
        diagnostics=diagnostics,
    ).as_dict(include_details=True)
    payload["classification"] = _classification_from_overall(str(payload["overall"]))
    return payload


def build_service(config: HomeWakeConfig) -> HomeWakeService:
    """Build a Wyoming-facing service from manifest-backed runtime inputs."""

    manifest_path = resolve_manifest_path(config)
    base_registry = load_registry(manifest_path, require_artifact=True)
    custom_imports = import_custom_model_bundles(
        config.custom_models,
        base_registry=base_registry,
    )
    registry = merge_registries(base_registry, custom_imports.manifests)
    manifest = registry.resolve(config.detector.backend)
    service_config = build_service_config(config, manifest)
    inventory = registry.inventory(verify_hash=True)
    config_echo = build_config_echo(service_config)
    detector = BCResNetDetector(
        config=service_config.detector,
        manifest=manifest,
        audio_config=service_config.audio,
    )
    runtime = WyomingRuntime(config=service_config, detector=detector)
    server = WyomingServer.from_runtime(
        runtime,
        loaded_wake_words=registry.list_wake_words(),
        inventory=inventory,
        config_echo=config_echo,
    )
    return HomeWakeService(
        config=service_config,
        registry=registry,
        manifest=manifest,
        inventory=inventory,
        custom_imports=custom_imports,
        config_echo=config_echo,
        server=server,
    )
