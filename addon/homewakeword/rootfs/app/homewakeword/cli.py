"""Command line entrypoint for the HomeWakeWord package."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import signal
import sys
import threading
import time
from typing import cast

from homewakeword.config import (
    CustomModelImportConfig,
    DetectorConfig,
    HomeWakeWordConfig,
    WyomingServerConfig,
)
from homewakeword.detector.bcresnet import BCResNetRuntimeError
from homewakeword.registry import ManifestValidationError
from homewakeword.runtime import build_service
from homewakeword.selftest import run_self_test


@dataclass(frozen=True, slots=True)
class ServeArgs:
    host: str
    port: int
    detector_backend: str
    manifest: Path | None
    custom_models: bool
    custom_model_dir: Path
    openwakeword_compat: bool
    openwakeword_model_dir: Path
    self_test: bool
    report: Path | None


def build_parser() -> argparse.ArgumentParser:
    """Build the HomeWakeWord CLI parser."""

    parser = argparse.ArgumentParser(
        prog="python -m homewakeword.cli",
        description="HomeWakeWord Wyoming-facing runtime shell.",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Start the Wyoming service")
    _ = serve.add_argument(
        "--host", default=HomeWakeWordConfig().server.host, help="Wyoming bind host"
    )
    _ = serve.add_argument(
        "--port",
        type=int,
        default=HomeWakeWordConfig().server.port,
        help="Wyoming bind port",
    )
    _ = serve.add_argument(
        "--detector-backend",
        default=HomeWakeWordConfig().detector.backend,
        help="Detector backend identifier",
    )
    _ = serve.add_argument(
        "--manifest",
        type=Path,
        default=HomeWakeWordConfig().detector.manifest_path,
        help="Path to the manifest/registry file",
    )
    _ = serve.add_argument(
        "--custom-models",
        action=argparse.BooleanOptionalAction,
        default=HomeWakeWordConfig().custom_models.enabled,
        help="Enable custom bundle imports from the primary shared directory",
    )
    _ = serve.add_argument(
        "--custom-model-dir",
        type=Path,
        default=HomeWakeWordConfig().custom_models.directory,
        help="Primary custom model bundle directory",
    )
    _ = serve.add_argument(
        "--openwakeword-compat",
        action=argparse.BooleanOptionalAction,
        default=HomeWakeWordConfig().custom_models.openwakeword_compat_enabled,
        help="Enable optional compatibility imports from /share/openwakeword",
    )
    _ = serve.add_argument(
        "--openwakeword-model-dir",
        type=Path,
        default=HomeWakeWordConfig().custom_models.openwakeword_directory,
        help="Compatibility custom model directory",
    )
    _ = serve.add_argument(
        "--self-test",
        action="store_true",
        help="Run a non-interactive startup and detection self-test",
    )
    _ = serve.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write the self-test report JSON to this path",
    )
    return parser


def _parse_serve_args(namespace: argparse.Namespace) -> ServeArgs:
    return ServeArgs(
        host=cast(str, namespace.host),
        port=cast(int, namespace.port),
        detector_backend=cast(str, namespace.detector_backend),
        manifest=cast(Path | None, namespace.manifest),
        custom_models=cast(bool, namespace.custom_models),
        custom_model_dir=cast(Path, namespace.custom_model_dir),
        openwakeword_compat=cast(bool, namespace.openwakeword_compat),
        openwakeword_model_dir=cast(Path, namespace.openwakeword_model_dir),
        self_test=cast(bool, namespace.self_test),
        report=cast(Path | None, namespace.report),
    )


def _build_config(args: ServeArgs) -> HomeWakeWordConfig:
    return HomeWakeWordConfig(
        detector=DetectorConfig(
            backend=args.detector_backend,
            manifest_path=args.manifest,
        ),
        custom_models=CustomModelImportConfig(
            enabled=args.custom_models,
            directory=args.custom_model_dir,
            openwakeword_compat_enabled=args.openwakeword_compat,
            openwakeword_directory=args.openwakeword_model_dir,
        ),
        server=WyomingServerConfig(host=args.host, port=args.port),
    )


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handle_signal(signum: int, frame: object | None) -> None:
        del signum, frame
        stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _handle_signal)


def _serve_forever(stop_event: threading.Event | None = None) -> None:
    local_stop_event = threading.Event() if stop_event is None else stop_event
    if stop_event is None:
        _install_signal_handlers(local_stop_event)
    while not local_stop_event.wait(timeout=1.0):
        time.sleep(0)


def _serve(args: argparse.Namespace) -> int:
    try:
        serve_args = _parse_serve_args(args)
        service = build_service(_build_config(serve_args))
        if serve_args.self_test:
            result = run_self_test(service, report_path=serve_args.report)
            print(
                f"self-test passed: wake_words={','.join(result.loaded_wake_words)} health={result.health_status} uri={result.service_uri}",
                flush=True,
            )
            return 0

        server = service.server
        server.start()
        try:
            description = server.describe()
            print(
                f"ready: uri={description.uri} wake_words={','.join(wake_word.name for wake_word in description.wake_words)}",
                flush=True,
            )
            _serve_forever()
        finally:
            server.stop()
    except (
        ManifestValidationError,
        BCResNetRuntimeError,
        LookupError,
        RuntimeError,
        OSError,
    ) as exc:
        print(str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the requested HomeWakeWord CLI command."""

    parser = build_parser()
    args = parser.parse_args(argv)
    command = cast(str | None, args.command)
    if command == "serve":
        return _serve(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
