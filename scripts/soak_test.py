from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
from typing import Any, Mapping, TypedDict

import yaml

from homewakeword.audio import iter_wave_chunks
from homewakeword.config import (
    CustomModelImportConfig,
    DetectorConfig,
    HomeWakeWordConfig,
    WyomingServerConfig,
)
from homewakeword.detector.bcresnet import BCResNetRuntimeError
from homewakeword.registry import ManifestValidationError
from homewakeword.runtime import (
    build_service,
    build_runtime_report,
    build_startup_failure_report,
    collect_process_resources,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / ".sisyphus" / "evidence" / "task-12-soak.json"
DEFAULT_CYCLES_PER_HOUR = 6
DEFAULT_STARTUP_LIMIT_MS = 250.0
MEMORY_GROWTH_LIMIT_PERCENT = 20.0


class SoakCase(TypedDict):
    label: str
    input_path: str
    expect: str


class UpgradePlan(TypedDict):
    baseline_manifest: str
    baseline_input: str
    baseline_expect: str
    valid_manifest: str
    valid_input: str
    valid_expect: str
    invalid_manifest: str


class SoakPlan(TypedDict):
    plan_path: Path
    cycles_per_hour: int
    startup_limit_ms: float
    addon_restart_attempts: int
    cases: list[SoakCase]
    upgrade: UpgradePlan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.soak_test")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--hours", type=float, required=True)
    parser.add_argument("--report", type=Path, default=DEFAULT_OUTPUT)
    return parser


def _require_mapping(value: object, *, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be a mapping")
    return value


def _require_list(value: object, *, context: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{context} must be a list")
    return value


def _require_string(value: object, *, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{context} must be a non-empty string")
    return value.strip()


def _require_number(value: object, *, context: str) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be numeric")
    return float(value)


def _resolve_path(root: Path, raw_path: object, *, context: str) -> Path:
    path = Path(_require_string(raw_path, context=context))
    if not path.is_absolute():
        path = (root / path).resolve()
    return path


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000.0, 3)


def _materialize_manifest(source_manifest: Path, target_manifest: Path) -> None:
    raw = yaml.safe_load(source_manifest.read_text(encoding="utf-8")) or {}
    root = _require_mapping(raw, context=str(source_manifest))

    def _rewrite_paths(manifest_root: dict[str, object]) -> None:
        model_path = manifest_root.get("model_path")
        if isinstance(model_path, str) and not Path(model_path).is_absolute():
            manifest_root["model_path"] = str(
                (source_manifest.parent / model_path).resolve()
            )
        evaluation = manifest_root.get("evaluation")
        if not isinstance(evaluation, dict):
            return
        for key in ("positive_fixture", "negative_fixture"):
            value = evaluation.get(key)
            if isinstance(value, str) and not Path(value).is_absolute():
                evaluation[key] = str((source_manifest.parent / value).resolve())

    models = root.get("models")
    if isinstance(models, list):
        for raw_model in models:
            if isinstance(raw_model, dict):
                _rewrite_paths(raw_model)
    else:
        _rewrite_paths(root)
    target_manifest.write_text(
        yaml.safe_dump(root, sort_keys=False),
        encoding="utf-8",
    )


def _build_config(manifest_path: Path, *, port: int = 10400) -> HomeWakeWordConfig:
    return HomeWakeWordConfig(
        detector=DetectorConfig(manifest_path=manifest_path),
        custom_models=CustomModelImportConfig(enabled=False),
        server=WyomingServerConfig(host="127.0.0.1", port=port),
    )


def _exercise_audio_case(
    service, case: SoakCase, *, cycle_index: int | None = None
) -> dict[str, Any]:
    label = case["label"]
    input_path = Path(case["input_path"])
    expect = case["expect"]
    reset = getattr(service.server.runtime.detector, "reset", None)
    if callable(reset):
        reset()
    detected_labels: list[str] = []
    chunks = iter_wave_chunks(input_path, service.config.audio)
    for chunk in chunks:
        detection_event = service.server.handle_audio_chunk(chunk)
        if detection_event is not None:
            detected_labels.append(detection_event.wake_word)
    passed = detected_labels == [] if expect == "none" else detected_labels == [expect]
    result: dict[str, object] = {
        "label": label,
        "input": str(input_path),
        "expect": expect,
        "detected_labels": detected_labels,
        "chunk_count": len(chunks),
        "status": "pass" if passed else "fail",
    }
    if cycle_index is not None:
        result["cycle"] = cycle_index
    return result


def _run_cycle(
    manifest_path: Path,
    *,
    cases: list[SoakCase],
    cycle_index: int,
    startup_limit_ms: float,
) -> dict[str, Any]:
    cycle_started = time.perf_counter()
    config = _build_config(manifest_path, port=10400 + (cycle_index % 200))
    build_started = time.perf_counter()
    try:
        service = build_service(config)
        build_duration_ms = _elapsed_ms(build_started)
        start_started = time.perf_counter()
        service.server.start()
        startup_duration_ms = _elapsed_ms(start_started)
    except (BCResNetRuntimeError, ManifestValidationError, LookupError, OSError) as exc:
        startup_duration_ms = _elapsed_ms(build_started)
        return {
            "cycle": cycle_index,
            "status": "fail",
            "build_service_duration_ms": startup_duration_ms,
            "startup_duration_ms": startup_duration_ms,
            "startup_health": build_startup_failure_report(
                config,
                error=exc,
                startup_duration_ms=startup_duration_ms,
                notes=[f"cycle={cycle_index}", "phase=cycle_startup"],
            ),
            "shutdown_health": None,
            "cases": [],
            "cycle_duration_ms": _elapsed_ms(cycle_started),
            "assertions": {
                "startup_duration": {
                    "limit_ms": startup_limit_ms,
                    "measured_ms": startup_duration_ms,
                    "passed": False,
                }
            },
        }

    try:
        startup_health = build_runtime_report(
            service,
            startup_duration_ms=startup_duration_ms,
            notes=[
                f"cycle={cycle_index}",
                f"build_service_duration_ms={build_duration_ms}",
            ],
        )
        case_results = [
            _exercise_audio_case(service, case, cycle_index=cycle_index)
            for case in cases
        ]
        status = "pass"
        if startup_health.get("overall") != "ready":
            status = "fail"
        if startup_duration_ms > startup_limit_ms:
            status = "fail"
        if any(result["status"] != "pass" for result in case_results):
            status = "fail"
    except (BCResNetRuntimeError, ManifestValidationError, LookupError, OSError) as exc:
        startup_health = build_startup_failure_report(
            config,
            error=exc,
            startup_duration_ms=startup_duration_ms,
            notes=[f"cycle={cycle_index}", "phase=audio_replay"],
        )
        case_results = []
        status = "fail"
    finally:
        service.server.stop()

    shutdown_health = build_runtime_report(service, notes=[f"cycle={cycle_index}"])
    if shutdown_health.get("overall") != "degraded":
        status = "fail"
    return {
        "cycle": cycle_index,
        "status": status,
        "build_service_duration_ms": build_duration_ms,
        "startup_duration_ms": startup_duration_ms,
        "startup_health": startup_health,
        "shutdown_health": shutdown_health,
        "cases": case_results,
        "cycle_duration_ms": _elapsed_ms(cycle_started),
        "assertions": {
            "startup_duration": {
                "limit_ms": startup_limit_ms,
                "measured_ms": startup_duration_ms,
                "passed": startup_duration_ms <= startup_limit_ms,
            },
            "startup_health": {
                "expected": "ready",
                "measured": startup_health.get("overall"),
                "passed": startup_health.get("overall") == "ready",
            },
            "shutdown_health": {
                "expected": "degraded",
                "measured": shutdown_health.get("overall"),
                "passed": shutdown_health.get("overall") == "degraded",
            },
        },
    }


def _run_command(
    command: list[str], *, timeout_seconds: int = 600
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))
    except subprocess.TimeoutExpired as exc:
        stdout = "" if exc.stdout is None else str(exc.stdout)
        stderr = "" if exc.stderr is None else str(exc.stderr)
        return subprocess.CompletedProcess(command, 124, stdout, stderr)


def _run_addon_restart_check(attempts: int) -> dict[str, object]:
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        return {
            "status": "blocked",
            "code": "DOCKER_UNAVAILABLE",
            "detail": "docker is not available in this workspace; add-on restart check was not executed.",
            "attempts": [],
        }
    dockerfile = REPO_ROOT / "addon" / "homewakeword-bcresnet" / "Dockerfile"
    if not dockerfile.exists():
        return {
            "status": "blocked",
            "code": "ADDON_DOCKERFILE_MISSING",
            "detail": f"expected add-on Dockerfile is missing: {dockerfile}",
            "attempts": [],
        }
    image = "local/homewakeword:soak"
    build_result = _run_command(
        [docker_bin, "build", "-f", str(dockerfile), "-t", image, "."],
        timeout_seconds=900,
    )
    if build_result.returncode != 0:
        return {
            "status": "fail",
            "code": "ADDON_BUILD_FAILURE",
            "detail": build_result.stderr.strip() or "docker build failed",
            "attempts": [],
        }
    runs: list[dict[str, object]] = []
    for attempt in range(1, attempts + 1):
        result = _run_command(
            [docker_bin, "run", "--rm", image, "--self-test"],
            timeout_seconds=180,
        )
        runs.append(
            {
                "attempt": attempt,
                "exit_code": result.returncode,
                "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip(),
            }
        )
        if result.returncode != 0:
            return {
                "status": "fail",
                "code": "ADDON_SELF_TEST_FAILURE",
                "detail": result.stderr.strip() or "container self-test failed",
                "attempts": runs,
            }
    return {
        "status": "pass",
        "code": "ADDON_RESTART_OK",
        "detail": f"container self-test passed {attempts} consecutive restart attempts",
        "attempts": runs,
    }


def _write_swap_error_log(error_path: Path, invalid_swap: Mapping[str, Any]) -> None:
    error_path.parent.mkdir(parents=True, exist_ok=True)
    payload = invalid_swap.get("failure_report")
    serialized = ""
    if isinstance(payload, dict):
        serialized = json.dumps(payload, indent=2, sort_keys=True)
    active_detection = invalid_swap.get("active_detection")
    active_detection_status = (
        None
        if not isinstance(active_detection, dict)
        else active_detection.get("status")
    )
    error_path.write_text(
        (
            "invalid model swap failed safely\n"
            f"status={invalid_swap.get('status')}\n"
            f"detail={invalid_swap.get('detail')}\n"
            f"active_service_healthy={invalid_swap.get('active_service_healthy')}\n"
            f"active_detection_status={active_detection_status}\n"
            f"failure_report={serialized}\n"
        ),
        encoding="utf-8",
    )


def _run_upgrade_checks(
    input_dir: Path,
    upgrade: UpgradePlan,
    *,
    error_log_path: Path,
) -> dict[str, Any]:
    with TemporaryDirectory() as tmpdir:
        temp_manifest = Path(tmpdir) / "manifest.yaml"
        baseline_source = Path(str(upgrade["baseline_manifest"]))
        valid_source = Path(str(upgrade["valid_manifest"]))
        invalid_source = Path(str(upgrade["invalid_manifest"]))
        _materialize_manifest(baseline_source, temp_manifest)
        baseline_config = _build_config(temp_manifest, port=10990)
        baseline_service = build_service(baseline_config)
        baseline_service.server.start()
        try:
            baseline_result = _exercise_audio_case(
                baseline_service,
                {
                    "label": "upgrade-baseline",
                    "input_path": str(Path(str(upgrade["baseline_input"]))),
                    "expect": str(upgrade["baseline_expect"]),
                },
            )
            baseline_health = build_runtime_report(
                baseline_service,
                notes=["phase=upgrade_baseline"],
            )
            baseline_status = (
                "pass"
                if baseline_result["status"] == "pass"
                and baseline_health.get("overall") == "ready"
                else "fail"
            )
            _materialize_manifest(valid_source, temp_manifest)
        finally:
            baseline_service.server.stop()

        valid_config = _build_config(temp_manifest, port=10991)
        valid_service = build_service(valid_config)
        valid_service.server.start()
        try:
            valid_result = _exercise_audio_case(
                valid_service,
                {
                    "label": "upgrade-valid-swap",
                    "input_path": str(Path(str(upgrade["valid_input"]))),
                    "expect": str(upgrade["valid_expect"]),
                },
            )
            valid_health = build_runtime_report(
                valid_service,
                notes=["phase=upgrade_valid_swap"],
            )
            valid_status = (
                "pass"
                if valid_result["status"] == "pass"
                and valid_health.get("overall") == "ready"
                else "fail"
            )
            _materialize_manifest(invalid_source, temp_manifest)
            invalid_started = time.perf_counter()
            invalid_detail = "replacement unexpectedly loaded"
            failure_report: dict[str, object] | None = None
            invalid_status = "fail"
            try:
                _ = build_service(_build_config(temp_manifest, port=10992))
            except (
                BCResNetRuntimeError,
                ManifestValidationError,
                LookupError,
                OSError,
            ) as exc:
                invalid_duration_ms = _elapsed_ms(invalid_started)
                failure_report = build_startup_failure_report(
                    _build_config(temp_manifest, port=10992),
                    error=exc,
                    startup_duration_ms=invalid_duration_ms,
                    notes=["phase=upgrade_invalid_swap"],
                )
                invalid_detail = str(exc)
                invalid_status = "pass"
            active_health = build_runtime_report(
                valid_service,
                notes=["phase=upgrade_invalid_swap_active_service"],
            )
            active_detection = _exercise_audio_case(
                valid_service,
                {
                    "label": "upgrade-active-service-after-invalid-swap",
                    "input_path": str(Path(str(upgrade["valid_input"]))),
                    "expect": str(upgrade["valid_expect"]),
                },
            )
        finally:
            valid_service.server.stop()

    invalid_swap = {
        "status": (
            "pass"
            if invalid_status == "pass"
            and active_health.get("overall") == "ready"
            and active_detection["status"] == "pass"
            else "fail"
        ),
        "detail": invalid_detail,
        "failure_report": failure_report,
        "active_service_healthy": active_health.get("overall") == "ready",
        "active_service_health": active_health,
        "active_detection": active_detection,
    }
    _write_swap_error_log(error_log_path, invalid_swap)
    return {
        "baseline_restart": {
            "status": baseline_status,
            "health": baseline_health,
            "detection": baseline_result,
        },
        "valid_model_restart": {
            "status": valid_status,
            "health": valid_health,
            "detection": valid_result,
        },
        "invalid_model_swap": invalid_swap,
        "artifacts": {"error_log": str(error_log_path)},
    }


def _load_plan(input_dir: Path) -> SoakPlan:
    plan_path = input_dir / "cases.yaml"
    raw = yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
    root = _require_mapping(raw, context=str(plan_path))
    cases = []
    for index, raw_case in enumerate(
        _require_list(root.get("cases"), context="cases"), start=1
    ):
        case = _require_mapping(raw_case, context=f"cases[{index}]")
        cases.append(
            {
                "label": _require_string(
                    case.get("label"), context=f"cases[{index}].label"
                ),
                "input_path": str(
                    _resolve_path(
                        input_dir,
                        case.get("input"),
                        context=f"cases[{index}].input",
                    )
                ),
                "expect": _require_string(
                    case.get("expect"), context=f"cases[{index}].expect"
                ),
            }
        )
    upgrade_root = _require_mapping(root.get("upgrade"), context="upgrade")
    return {
        "plan_path": plan_path,
        "cycles_per_hour": int(
            _require_number(
                root.get("cycles_per_hour", DEFAULT_CYCLES_PER_HOUR),
                context="cycles_per_hour",
            )
        ),
        "startup_limit_ms": _require_number(
            root.get("startup_limit_ms", DEFAULT_STARTUP_LIMIT_MS),
            context="startup_limit_ms",
        ),
        "addon_restart_attempts": int(
            _require_number(
                root.get("addon_restart_attempts", 2),
                context="addon_restart_attempts",
            )
        ),
        "cases": cases,
        "upgrade": {
            "baseline_manifest": str(
                _resolve_path(
                    input_dir,
                    upgrade_root.get("baseline_manifest"),
                    context="upgrade.baseline_manifest",
                )
            ),
            "baseline_input": str(
                _resolve_path(
                    input_dir,
                    upgrade_root.get("baseline_input"),
                    context="upgrade.baseline_input",
                )
            ),
            "baseline_expect": _require_string(
                upgrade_root.get("baseline_expect"),
                context="upgrade.baseline_expect",
            ),
            "valid_manifest": str(
                _resolve_path(
                    input_dir,
                    upgrade_root.get("valid_manifest"),
                    context="upgrade.valid_manifest",
                )
            ),
            "valid_input": str(
                _resolve_path(
                    input_dir,
                    upgrade_root.get("valid_input"),
                    context="upgrade.valid_input",
                )
            ),
            "valid_expect": _require_string(
                upgrade_root.get("valid_expect"),
                context="upgrade.valid_expect",
            ),
            "invalid_manifest": str(
                _resolve_path(
                    input_dir,
                    upgrade_root.get("invalid_manifest"),
                    context="upgrade.invalid_manifest",
                )
            ),
        },
    }


def soak_test(
    manifest_path: Path,
    *,
    input_dir: Path,
    hours: float,
    report_path: Path,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    plan = _load_plan(input_dir)
    cycles_per_hour = int(plan["cycles_per_hour"])
    startup_limit_ms = float(plan["startup_limit_ms"])
    target_cycles = max(1, int(math.ceil(hours * cycles_per_hour)))
    baseline_resources = collect_process_resources()
    cycle_results = [
        _run_cycle(
            manifest_path,
            cases=list(plan["cases"]),
            cycle_index=index,
            startup_limit_ms=startup_limit_ms,
        )
        for index in range(1, target_cycles + 1)
    ]
    final_resources = collect_process_resources()
    error_log_path = report_path.with_name(report_path.stem + "-error.txt")
    upgrade_checks = _run_upgrade_checks(
        input_dir,
        plan["upgrade"],
        error_log_path=error_log_path,
    )
    addon_restart = _run_addon_restart_check(int(plan["addon_restart_attempts"]))

    rss_samples: list[int] = []
    steady_state_rss: list[int] = []
    startup_samples: list[float] = []
    for sample in (baseline_resources, final_resources):
        rss = sample.get("rss_bytes")
        if isinstance(rss, int):
            rss_samples.append(rss)
    for cycle in cycle_results:
        startup_duration_ms = cycle.get("startup_duration_ms")
        if isinstance(startup_duration_ms, (int, float)):
            startup_samples.append(float(startup_duration_ms))
        for health_key in ("startup_health", "shutdown_health"):
            health = cycle.get(health_key)
            if not isinstance(health, dict):
                continue
            diagnostics = health.get("diagnostics")
            if not isinstance(diagnostics, dict):
                continue
            resources = diagnostics.get("process_resources")
            if not isinstance(resources, dict):
                continue
            rss = resources.get("rss_bytes")
            if isinstance(rss, int):
                rss_samples.append(rss)
                if health_key == "shutdown_health":
                    steady_state_rss.append(rss)
    baseline_rss = baseline_resources.get("rss_bytes")
    peak_rss = max(rss_samples) if rss_samples else 0
    memory_growth_percent = 0.0
    if isinstance(baseline_rss, int) and baseline_rss > 0 and peak_rss > 0:
        memory_growth_percent = round(
            ((peak_rss - baseline_rss) / baseline_rss) * 100.0,
            3,
        )
    cycle_failures = [cycle for cycle in cycle_results if cycle["status"] != "pass"]
    upgrade_failures = [
        section
        for section in ("baseline_restart", "valid_model_restart", "invalid_model_swap")
        if upgrade_checks[section]["status"] != "pass"
    ]
    limitations: list[str] = []
    if addon_restart["status"] == "blocked":
        limitations.append(str(addon_restart["detail"]))
    report: dict[str, Any] = {
        "verdict": "pass",
        "status": "ok",
        "manifest": str(manifest_path),
        "input_dir": str(input_dir),
        "methodology": {
            "mode": "accelerated_fixture_cycles",
            "requested_hours": hours,
            "cycles_per_hour": cycles_per_hour,
            "target_cycles": target_cycles,
            "completed_cycles": len(cycle_results),
            "virtual_minutes_per_cycle": round(60.0 / cycles_per_hour, 3),
            "wall_clock_seconds": round(time.perf_counter() - started_at, 3),
            "notes": [
                "This command measures repeated in-process start/stop cycles and WAV replay using fixture audio paths.",
                "The requested soak hours are accelerated into repeated fixture cycles; wall-clock duration is reported separately and not claimed as literal six-hour runtime.",
            ],
            "plan": str(plan["plan_path"]),
        },
        "assertions": {
            "memory_growth": {
                "limit_percent": MEMORY_GROWTH_LIMIT_PERCENT,
                "measured_percent": memory_growth_percent,
                "passed": memory_growth_percent <= MEMORY_GROWTH_LIMIT_PERCENT,
            },
            "startup_duration": {
                "limit_ms": startup_limit_ms,
                "max_ms": None
                if not startup_samples
                else round(max(startup_samples), 3),
                "avg_ms": None
                if not startup_samples
                else round(sum(startup_samples) / len(startup_samples), 3),
                "passed": bool(startup_samples)
                and max(startup_samples) <= startup_limit_ms,
            },
            "cycle_completion": {
                "expected": target_cycles,
                "completed": len(cycle_results),
                "passed": len(cycle_results) == target_cycles,
            },
        },
        "resource_usage": {
            "baseline": baseline_resources,
            "final": final_resources,
            "peak_rss_bytes": peak_rss,
            "steady_state_average_rss_bytes": None
            if not steady_state_rss
            else round(sum(steady_state_rss) / len(steady_state_rss)),
            "memory_growth_percent": memory_growth_percent,
        },
        "cycle_summary": {
            "total": len(cycle_results),
            "failed": len(cycle_failures),
            "passed": len(cycle_results) - len(cycle_failures),
        },
        "cycles": cycle_results,
        "upgrade_checks": upgrade_checks,
        "addon_restart": addon_restart,
        "artifacts": {
            "report": str(report_path),
            "invalid_swap_error_log": str(error_log_path),
        },
        "limitations": limitations,
    }
    if cycle_failures or upgrade_failures or addon_restart["status"] == "fail":
        report["verdict"] = "fail"
        report["status"] = "failed"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = soak_test(
            args.manifest,
            input_dir=args.input_dir,
            hours=args.hours,
            report_path=args.report,
        )
    except (LookupError, OSError, ValueError, yaml.YAMLError) as exc:
        print(str(exc))
        return 1
    print(
        f"soak test completed: verdict={report['verdict']} cycles={report['cycle_summary']['total']} output={args.report}"
    )
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
