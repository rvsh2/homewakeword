from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
from typing import Any, TypedDict, cast

import yaml

from homewake.config import (
    CustomModelImportConfig,
    DetectorConfig,
    HomeWakeConfig,
    WyomingServerConfig,
)
from homewake.detector.bcresnet import BCResNetRuntimeError
from homewake.registry import ManifestValidationError, load_registry
from homewake.runtime import build_service
from homewake.selftest import run_self_test
from scripts.replay_stream import main as replay_stream_main


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "models" / "manifest.yaml"
DEFAULT_ADDON_DOCKERFILE = REPO_ROOT / "addon" / "homewake-bcresnet" / "Dockerfile"
DEFAULT_HARNESS = (
    REPO_ROOT / "tests" / "harness" / "ha-supervised" / "docker-compose.yml"
)
READY_LINE_RE = re.compile(r"ready: uri=(?P<uri>\S+) wake_words=(?P<wake_words>.*)$")
SUBSYSTEM_KEYS = (
    "audio_replay",
    "detector_runtime",
    "wyoming_service",
    "addon_packaging",
    "artifact_loading",
    "ha_harness",
)


class ReplayProbeResult(TypedDict):
    status: str
    code: str
    detail: str
    subsystem: str
    artifact: Path
    log: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.ha_smoke")
    _ = parser.add_argument("--harness", type=Path, required=True)
    _ = parser.add_argument("--addon-slug", required=True)
    _ = parser.add_argument("--addon-image", required=True)
    _ = parser.add_argument("--wyoming-port", type=int, required=True)
    _ = parser.add_argument("--report", type=Path, required=True)
    return parser


def _new_subsystem() -> dict[str, object]:
    return {
        "status": "not_run",
        "code": "NOT_RUN",
        "detail": "step not executed",
        "artifacts": [],
        "logs": [],
    }


def _new_report(
    *,
    harness_path: Path,
    addon_slug: str,
    addon_image: str,
    wyoming_port: int,
    report_path: Path,
    manifest_path: Path,
) -> dict[str, object]:
    return {
        "verdict": "not_run",
        "manifest": str(manifest_path),
        "harness": str(harness_path),
        "addon_slug": addon_slug,
        "addon_image": addon_image,
        "wyoming_port": wyoming_port,
        "verification_mode": "replay + in-process runtime + add-on container + best-effort ha harness",
        "subsystems": {key: _new_subsystem() for key in SUBSYSTEM_KEYS},
        "artifacts": {"report": str(report_path)},
        "notes": [],
    }


def _append_unique(bucket: dict[str, object], key: str, values: list[str]) -> None:
    existing = bucket.get(key)
    items = [] if not isinstance(existing, list) else [str(value) for value in existing]
    for value in values:
        if value not in items:
            items.append(value)
    bucket[key] = items


def _set_subsystem(
    report: dict[str, object],
    key: str,
    *,
    status: str,
    code: str,
    detail: str,
    artifacts: list[Path] | None = None,
    logs: list[Path] | None = None,
) -> None:
    subsystems = report["subsystems"]
    if not isinstance(subsystems, dict):
        return
    subsystem = subsystems.get(key)
    if not isinstance(subsystem, dict):
        return
    subsystem = cast(dict[str, object], subsystem)
    subsystem["status"] = status
    subsystem["code"] = code
    subsystem["detail"] = detail
    if artifacts:
        _append_unique(subsystem, "artifacts", [str(path) for path in artifacts])
    if logs:
        _append_unique(subsystem, "logs", [str(path) for path in logs])


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(content, encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return cast(dict[str, Any], payload)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _ = path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _command_log(
    command: list[str], *, returncode: int, stdout: str, stderr: str
) -> str:
    rendered = " ".join(shlex.quote(part) for part in command)
    return (
        f"$ {rendered}\n"
        f"exit_code={returncode}\n"
        "--- stdout ---\n"
        f"{stdout}\n"
        "--- stderr ---\n"
        f"{stderr}\n"
    )


def _run_command(
    command: list[str],
    *,
    log_path: Path,
    cwd: Path = REPO_ROOT,
    timeout_seconds: int = 120,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        completed = subprocess.CompletedProcess(command, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = "" if exc.stdout is None else str(exc.stdout)
        stderr = "" if exc.stderr is None else str(exc.stderr)
        completed = subprocess.CompletedProcess(
            command, 124, stdout, stderr + "\ncommand timed out"
        )
    _write_text(
        log_path,
        _command_log(
            command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        ),
    )
    return completed


def _classify_runtime_issue(message: str) -> tuple[str, str]:
    normalized = message.lower()
    if any(
        token in normalized
        for token in (
            "model artifact does not exist",
            "evaluation positive fixture does not exist",
            "evaluation negative fixture does not exist",
            "hash verification failed",
            "detector manifests must define 'model_path'",
        )
    ):
        return "artifact_loading", "ARTIFACT_LOADING_FAILURE"
    if any(
        token in normalized
        for token in (
            "unsupported sample rate",
            "unsupported sample width",
            "unsupported channel count",
            "pcm16",
            "window samples",
            "wave",
        )
    ):
        return "audio_replay", "AUDIO_REPLAY_FAILURE"
    if "docker" in normalized:
        return "addon_packaging", "ADDON_PACKAGING_FAILURE"
    if any(
        token in normalized
        for token in ("self-test did not emit", "detector", "runtime", "manifest")
    ):
        return "detector_runtime", "DETECTOR_RUNTIME_FAILURE"
    return "detector_runtime", "DETECTOR_RUNTIME_FAILURE"


def _resolve_default_model(manifest_path: Path) -> tuple[str, Path, Path]:
    registry = load_registry(manifest_path, require_artifact=True)
    manifest = registry.default_model
    if manifest.evaluation is None:
        raise ManifestValidationError(
            "default manifest does not define evaluation fixtures"
        )
    return (
        manifest.wake_word,
        manifest.evaluation.positive_fixture,
        manifest.evaluation.negative_fixture,
    )


def run_replay_probe(
    manifest_path: Path,
    *,
    wake_word: str,
    input_path: Path,
    expect: str,
    json_out: Path,
    log_path: Path,
) -> ReplayProbeResult:
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
        exit_code = replay_stream_main(
            [
                "--manifest",
                str(manifest_path),
                "--wake-word",
                wake_word,
                "--input",
                str(input_path),
                "--expect",
                expect,
                "--json-out",
                str(json_out),
            ]
        )
    log_content = _command_log(
        [
            "python",
            "-m",
            "scripts.replay_stream",
            "--manifest",
            str(manifest_path),
            "--wake-word",
            wake_word,
            "--input",
            str(input_path),
            "--expect",
            expect,
            "--json-out",
            str(json_out),
        ],
        returncode=exit_code,
        stdout=stdout_buffer.getvalue(),
        stderr=stderr_buffer.getvalue(),
    )
    _write_text(log_path, log_content)
    if exit_code == 0:
        return {
            "status": "pass",
            "code": "AUDIO_REPLAY_OK",
            "detail": f"replay succeeded for {input_path.name}",
            "subsystem": "audio_replay",
            "artifact": json_out,
            "log": log_path,
        }
    subsystem, code = _classify_runtime_issue(stderr_buffer.getvalue())
    return {
        "status": "fail",
        "code": code,
        "detail": stderr_buffer.getvalue().strip() or "replay probe failed",
        "subsystem": subsystem,
        "artifact": json_out,
        "log": log_path,
    }


def _run_wyoming_self_test(
    manifest_path: Path,
    *,
    report_path: Path,
    wyoming_port: int,
) -> dict[str, Any]:
    service = build_service(
        HomeWakeConfig(
            detector=DetectorConfig(manifest_path=manifest_path),
            custom_models=CustomModelImportConfig(enabled=False),
            server=WyomingServerConfig(host="127.0.0.1", port=wyoming_port),
        )
    )
    result = run_self_test(service, report_path=report_path)
    return result.as_dict()


def _build_addon_options(port: int) -> dict[str, object]:
    return {
        "host": "0.0.0.0",
        "port": port,
        "detector_backend": "bcresnet",
        "manifest": "/app/models/manifest.yaml",
        "custom_models": False,
        "custom_model_dir": "/share/homewake/models",
        "openwakeword_compat": False,
        "openwakeword_model_dir": "/share/openwakeword",
        "log_level": "info",
    }


def _docker_compose_command() -> list[str] | None:
    docker_bin = shutil.which("docker")
    if docker_bin is not None:
        try:
            completed = subprocess.run(
                [docker_bin, "compose", "version"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            completed = None
        if completed is not None and completed.returncode == 0:
            return [docker_bin, "compose"]
    compose_bin = shutil.which("docker-compose")
    if compose_bin is not None:
        return [compose_bin]
    return None


def _parse_ready_line(log_text: str) -> tuple[str | None, list[str]]:
    for line in log_text.splitlines():
        match = READY_LINE_RE.search(line.strip())
        if match is None:
            continue
        raw_wake_words = match.group("wake_words").strip()
        wake_words = [item for item in raw_wake_words.split(",") if item]
        return match.group("uri"), wake_words
    return None, []


def _load_harness_shape(harness_path: Path) -> tuple[dict[str, Any], list[str]]:
    try:
        raw = yaml.safe_load(harness_path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        return {}, [str(exc)]
    if not isinstance(raw, dict):
        return {}, [f"harness root must be a mapping: {harness_path}"]
    services = raw.get("services")
    if not isinstance(services, dict):
        return {}, ["harness must declare compose services"]

    errors: list[str] = []
    if "ha_supervisor" not in services:
        errors.append("harness must define an ha_supervisor service")
    if "homeassistant" not in services:
        errors.append("harness must define a homeassistant service")
    if "addon_registry" not in services:
        errors.append("harness must define an addon_registry service")

    supervisor = services.get("ha_supervisor")
    if isinstance(supervisor, dict):
        if supervisor.get("privileged") is not True:
            errors.append("ha_supervisor must run privileged=true")
        volumes = supervisor.get("volumes")
        volume_entries = volumes if isinstance(volumes, list) else []
        if not any("/var/run/docker.sock" in str(entry) for entry in volume_entries):
            errors.append("ha_supervisor must mount /var/run/docker.sock")
    else:
        errors.append("ha_supervisor service must be a mapping")
    return cast(dict[str, Any], raw), errors


def _ensure_addon_image(
    addon_image: str,
    *,
    evidence_root: Path,
) -> tuple[bool, list[Path], str]:
    inspect_log = evidence_root / "ha-smoke-docker-inspect.log"
    inspect_result = _run_command(
        ["docker", "image", "inspect", addon_image],
        log_path=inspect_log,
        timeout_seconds=60,
    )
    logs = [inspect_log]
    if inspect_result.returncode == 0:
        return True, logs, f"using prebuilt add-on image {addon_image}"

    build_log = evidence_root / "ha-smoke-docker-build.log"
    build_result = _run_command(
        [
            "docker",
            "build",
            "-f",
            str(DEFAULT_ADDON_DOCKERFILE),
            "-t",
            addon_image,
            str(REPO_ROOT),
        ],
        log_path=build_log,
        timeout_seconds=600,
    )
    logs.append(build_log)
    if build_result.returncode == 0:
        return True, logs, f"built add-on image {addon_image}"
    detail = (
        build_result.stderr.strip()
        or build_result.stdout.strip()
        or "docker build failed"
    )
    return False, logs, detail


def ha_smoke(
    harness_path: Path,
    *,
    addon_slug: str,
    addon_image: str,
    wyoming_port: int,
    report_path: Path,
    manifest_path: Path = DEFAULT_MANIFEST,
) -> dict[str, object]:
    evidence_root = report_path.parent
    evidence_root.mkdir(parents=True, exist_ok=True)
    report = _new_report(
        harness_path=harness_path,
        addon_slug=addon_slug,
        addon_image=addon_image,
        wyoming_port=wyoming_port,
        report_path=report_path,
        manifest_path=manifest_path,
    )

    try:
        wake_word, positive_fixture, negative_fixture = _resolve_default_model(
            manifest_path
        )
    except (LookupError, ManifestValidationError, OSError) as exc:
        subsystem, code = _classify_runtime_issue(str(exc))
        _set_subsystem(
            report,
            subsystem,
            status="fail",
            code=code,
            detail=str(exc),
        )
        report["verdict"] = "fail"
        _write_json(report_path, report)
        return report
    _set_subsystem(
        report,
        "artifact_loading",
        status="pass",
        code="ARTIFACT_LOADING_OK",
        detail=(
            "manifest registry, packaged artifact, and evaluation fixtures resolved "
            f"for default wake word {wake_word}"
        ),
    )

    positive_json = evidence_root / "ha-smoke-replay-positive.json"
    positive_log = evidence_root / "ha-smoke-replay-positive.log"
    positive_probe = run_replay_probe(
        manifest_path,
        wake_word=wake_word,
        input_path=positive_fixture,
        expect=wake_word,
        json_out=positive_json,
        log_path=positive_log,
    )
    _set_subsystem(
        report,
        positive_probe["subsystem"],
        status=positive_probe["status"],
        code=positive_probe["code"],
        detail=positive_probe["detail"],
        artifacts=[positive_probe["artifact"]],
        logs=[positive_probe["log"]],
    )
    artifacts = report["artifacts"]
    if isinstance(artifacts, dict):
        artifacts["replay_positive"] = str(positive_json)

    negative_json = evidence_root / "ha-smoke-replay-negative.json"
    negative_log = evidence_root / "ha-smoke-replay-negative.log"
    negative_probe = run_replay_probe(
        manifest_path,
        wake_word=wake_word,
        input_path=negative_fixture,
        expect="none",
        json_out=negative_json,
        log_path=negative_log,
    )
    negative_subsystem = str(negative_probe["subsystem"])
    if str(negative_probe["status"]) == "fail":
        _set_subsystem(
            report,
            negative_subsystem,
            status=negative_probe["status"],
            code=negative_probe["code"],
            detail=negative_probe["detail"],
            artifacts=[negative_probe["artifact"]],
            logs=[negative_probe["log"]],
        )
    elif negative_subsystem == "audio_replay":
        _set_subsystem(
            report,
            "audio_replay",
            status="pass",
            code="AUDIO_REPLAY_OK",
            detail=f"positive and negative replay fixtures succeeded for {wake_word}",
            artifacts=[positive_json, negative_json],
            logs=[positive_log, negative_log],
        )
    if isinstance(artifacts, dict):
        artifacts["replay_negative"] = str(negative_json)

    wyoming_report_path = evidence_root / "ha-smoke-wyoming-self-test.json"
    try:
        wyoming_payload = _run_wyoming_self_test(
            manifest_path,
            report_path=wyoming_report_path,
            wyoming_port=wyoming_port,
        )
        _set_subsystem(
            report,
            "detector_runtime",
            status="pass",
            code="DETECTOR_RUNTIME_OK",
            detail="runtime self-test emitted a detection event",
            artifacts=[wyoming_report_path],
        )
        _set_subsystem(
            report,
            "wyoming_service",
            status="pass",
            code="WYOMING_SERVICE_OK",
            detail=(
                "runtime self-test described the Wyoming surface at "
                f"{wyoming_payload['service_uri']} with wake words "
                f"{', '.join(str(item) for item in wyoming_payload['loaded_wake_words'])}"
            ),
            artifacts=[wyoming_report_path],
        )
        if isinstance(artifacts, dict):
            artifacts["wyoming_self_test"] = str(wyoming_report_path)
    except (
        ManifestValidationError,
        BCResNetRuntimeError,
        LookupError,
        OSError,
        RuntimeError,
    ) as exc:
        subsystem, code = _classify_runtime_issue(str(exc))
        _set_subsystem(
            report,
            subsystem,
            status="fail",
            code=code,
            detail=str(exc),
            artifacts=[wyoming_report_path],
        )

    if shutil.which("docker") is None:
        _set_subsystem(
            report,
            "addon_packaging",
            status="blocked",
            code="ADDON_PACKAGING_BLOCKED",
            detail="docker is not installed in this workspace",
        )
        _set_subsystem(
            report,
            "ha_harness",
            status="blocked",
            code="HA_HARNESS_UNAVAILABLE",
            detail="docker is not installed, so the supervised harness cannot boot",
        )
    else:
        built, build_logs, build_detail = _ensure_addon_image(
            addon_image, evidence_root=evidence_root
        )
        if not built:
            _set_subsystem(
                report,
                "addon_packaging",
                status="fail",
                code="ADDON_PACKAGING_FAILURE",
                detail=build_detail,
                logs=build_logs,
            )
        else:
            with TemporaryDirectory() as tmpdir:
                temp_root = Path(tmpdir)
                data_dir = temp_root / "data"
                data_dir.mkdir(parents=True, exist_ok=True)
                options_path = data_dir / "options.json"
                _ = options_path.write_text(
                    json.dumps(
                        _build_addon_options(wyoming_port), indent=2, sort_keys=True
                    )
                    + "\n",
                    encoding="utf-8",
                )

                addon_self_test_path = evidence_root / "ha-smoke-addon-self-test.json"
                addon_self_test_log = evidence_root / "ha-smoke-addon-self-test.log"
                self_test_run = _run_command(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "-v",
                        f"{data_dir}:/data",
                        "-v",
                        f"{evidence_root}:/reports",
                        addon_image,
                        "--self-test",
                        "--report",
                        f"/reports/{addon_self_test_path.name}",
                    ],
                    log_path=addon_self_test_log,
                    timeout_seconds=240,
                )
                addon_logs = build_logs + [addon_self_test_log]
                if self_test_run.returncode != 0:
                    subsystem, code = _classify_runtime_issue(
                        self_test_run.stderr.strip() or self_test_run.stdout.strip()
                    )
                    _set_subsystem(
                        report,
                        subsystem,
                        status="fail",
                        code=code,
                        detail=self_test_run.stderr.strip()
                        or self_test_run.stdout.strip()
                        or "add-on self-test failed",
                        artifacts=[addon_self_test_path],
                        logs=addon_logs,
                    )
                else:
                    _ = _read_json(addon_self_test_path)
                    _set_subsystem(
                        report,
                        "addon_packaging",
                        status="pass",
                        code="ADDON_PACKAGING_OK",
                        detail=f"container self-test succeeded for {addon_image}",
                        artifacts=[addon_self_test_path],
                        logs=addon_logs,
                    )
                    if isinstance(artifacts, dict):
                        artifacts["addon_self_test"] = str(addon_self_test_path)

                    container_name = f"{addon_slug}-smoke-{int(time.time())}"
                    addon_ready_log = evidence_root / "ha-smoke-addon-ready.log"
                    try:
                        start_result = _run_command(
                            [
                                "docker",
                                "run",
                                "-d",
                                "--name",
                                container_name,
                                "-v",
                                f"{data_dir}:/data",
                                addon_image,
                            ],
                            log_path=evidence_root / "ha-smoke-addon-run.log",
                            timeout_seconds=60,
                        )
                        addon_logs.append(evidence_root / "ha-smoke-addon-run.log")
                        if start_result.returncode == 0:
                            time.sleep(2)
                            logs_result = _run_command(
                                ["docker", "logs", container_name],
                                log_path=addon_ready_log,
                                timeout_seconds=60,
                            )
                            addon_logs.append(addon_ready_log)
                            service_uri, wake_words = _parse_ready_line(
                                logs_result.stdout
                            )
                            if service_uri is not None:
                                _set_subsystem(
                                    report,
                                    "wyoming_service",
                                    status="pass",
                                    code="WYOMING_SERVICE_OK",
                                    detail=(
                                        "add-on container reported Wyoming readiness at "
                                        f"{service_uri} with wake words {', '.join(wake_words)}"
                                    ),
                                    artifacts=[addon_self_test_path],
                                    logs=addon_logs,
                                )
                                if isinstance(artifacts, dict):
                                    artifacts["addon_ready_log"] = str(addon_ready_log)
                            else:
                                _set_subsystem(
                                    report,
                                    "wyoming_service",
                                    status="fail",
                                    code="WYOMING_SERVICE_FAILURE",
                                    detail="add-on container did not emit a Wyoming readiness line",
                                    artifacts=[addon_self_test_path],
                                    logs=addon_logs,
                                )
                    finally:
                        _ = _run_command(
                            ["docker", "rm", "-f", container_name],
                            log_path=evidence_root / "ha-smoke-addon-cleanup.log",
                            timeout_seconds=30,
                        )

        harness_spec, harness_errors = _load_harness_shape(harness_path)
        if not harness_path.exists():
            _set_subsystem(
                report,
                "ha_harness",
                status="fail",
                code="HA_HARNESS_MISSING",
                detail=f"harness path does not exist: {harness_path}",
            )
        elif harness_errors:
            _set_subsystem(
                report,
                "ha_harness",
                status="fail",
                code="HA_HARNESS_INVALID",
                detail="; ".join(harness_errors),
            )
        else:
            compose_command = _docker_compose_command()
            if compose_command is None:
                _set_subsystem(
                    report,
                    "ha_harness",
                    status="blocked",
                    code="HA_HARNESS_UNAVAILABLE",
                    detail="docker compose is not available in this workspace",
                )
            else:
                compose_config_log = evidence_root / "ha-smoke-compose-config.log"
                compose_config = _run_command(
                    [*compose_command, "-f", str(harness_path), "config"],
                    log_path=compose_config_log,
                    timeout_seconds=60,
                )
                if compose_config.returncode != 0:
                    _set_subsystem(
                        report,
                        "ha_harness",
                        status="fail",
                        code="HA_HARNESS_INVALID",
                        detail=compose_config.stderr.strip()
                        or compose_config.stdout.strip()
                        or "docker compose config failed",
                        logs=[compose_config_log],
                    )
                else:
                    compose_up_log = evidence_root / "ha-smoke-compose-up.log"
                    compose_down_log = evidence_root / "ha-smoke-compose-down.log"
                    try:
                        compose_up = _run_command(
                            [*compose_command, "-f", str(harness_path), "up", "-d"],
                            log_path=compose_up_log,
                            timeout_seconds=300,
                        )
                        if compose_up.returncode != 0:
                            _set_subsystem(
                                report,
                                "ha_harness",
                                status="blocked",
                                code="HA_HARNESS_BOOT_BLOCKED",
                                detail=compose_up.stderr.strip()
                                or compose_up.stdout.strip()
                                or "docker compose up failed",
                                logs=[compose_config_log, compose_up_log],
                            )
                        else:
                            notes = report.get("notes")
                            if isinstance(notes, list):
                                notes.append(
                                    "Harness booted far enough for compose orchestration, but add-on installation stays best-effort because the workspace does not provide a scripted Supervisor API/bootstrap path."
                                )
                            registry_service_present = (
                                isinstance(harness_spec.get("services"), dict)
                                and "addon_registry" in harness_spec["services"]
                            )
                            if registry_service_present:
                                push_tag = f"localhost:5000/{addon_slug}:smoke"
                                tag_log = evidence_root / "ha-smoke-registry-tag.log"
                                push_log = evidence_root / "ha-smoke-registry-push.log"
                                tag_result = _run_command(
                                    ["docker", "tag", addon_image, push_tag],
                                    log_path=tag_log,
                                    timeout_seconds=60,
                                )
                                push_result = _run_command(
                                    ["docker", "push", push_tag],
                                    log_path=push_log,
                                    timeout_seconds=180,
                                )
                                if (
                                    tag_result.returncode == 0
                                    and push_result.returncode == 0
                                ):
                                    _set_subsystem(
                                        report,
                                        "ha_harness",
                                        status="blocked",
                                        code="HA_HARNESS_INSTALL_UNVERIFIED",
                                        detail=(
                                            "compose harness booted and the add-on image was pushed to the local registry, "
                                            "but Supervisor add-on installation/startup could not be verified non-interactively in this workspace"
                                        ),
                                        logs=[
                                            compose_config_log,
                                            compose_up_log,
                                            tag_log,
                                            push_log,
                                        ],
                                    )
                                else:
                                    _set_subsystem(
                                        report,
                                        "ha_harness",
                                        status="blocked",
                                        code="HA_HARNESS_BOOT_BLOCKED",
                                        detail=push_result.stderr.strip()
                                        or push_result.stdout.strip()
                                        or tag_result.stderr.strip()
                                        or tag_result.stdout.strip()
                                        or "local add-on registry registration failed",
                                        logs=[
                                            compose_config_log,
                                            compose_up_log,
                                            tag_log,
                                            push_log,
                                        ],
                                    )
                            else:
                                _set_subsystem(
                                    report,
                                    "ha_harness",
                                    status="blocked",
                                    code="HA_HARNESS_INSTALL_UNVERIFIED",
                                    detail=(
                                        "compose harness booted, but no addon_registry service was available for local image registration and Supervisor add-on installation was not verified"
                                    ),
                                    logs=[compose_config_log, compose_up_log],
                                )
                    finally:
                        _ = _run_command(
                            [
                                *compose_command,
                                "-f",
                                str(harness_path),
                                "down",
                                "-v",
                                "--remove-orphans",
                            ],
                            log_path=compose_down_log,
                            timeout_seconds=180,
                        )

    subsystem_values = report.get("subsystems")
    statuses: list[str] = []
    if isinstance(subsystem_values, dict):
        statuses = [
            str(value.get("status"))
            for value in subsystem_values.values()
            if isinstance(value, dict) and value.get("status") not in {None, "not_run"}
        ]
    if any(status == "fail" for status in statuses):
        report["verdict"] = "fail"
    elif any(status == "blocked" for status in statuses):
        report["verdict"] = "blocked"
    else:
        report["verdict"] = "pass"
    _write_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ha_smoke(
        args.harness,
        addon_slug=args.addon_slug,
        addon_image=args.addon_image,
        wyoming_port=args.wyoming_port,
        report_path=args.report,
    )
    print(f"ha smoke report written: verdict={report['verdict']} output={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
