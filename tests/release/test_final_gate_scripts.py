from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from scripts.check_scope_fidelity import check_scope_fidelity
from scripts.final_runtime_validation import final_runtime_validation
from scripts.review_code_quality import review_code_quality
from scripts.verify_plan_compliance import audit_plan_compliance


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / "tests" / "fixtures" / "plans" / "implementation-plan.md"
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence"
MANIFEST_PATH = REPO_ROOT / "models" / "manifest.yaml"
ADDON_CONFIG = REPO_ROOT / "addon" / "homewakeword" / "config.yaml"


def test_review_code_quality_passes_for_task14_surface() -> None:
    report = review_code_quality(REPO_ROOT, pytest_report=None, soak_report=None)

    assert report["verdict"] == "pass"
    assert not report["failures"]


def test_scope_fidelity_passes_for_repo_docs_and_commit_gate() -> None:
    report = check_scope_fidelity(PLAN_PATH, REPO_ROOT)

    assert report["verdict"] == "pass"
    assert report["issues"] == []


def test_plan_compliance_marks_task14_deliverables_present() -> None:
    report = audit_plan_compliance(PLAN_PATH, REPO_ROOT, EVIDENCE_ROOT)
    tasks = cast(list[dict[str, Any]], report["tasks"])
    task14 = next(task for task in tasks if task["number"] == 14)

    assert task14["status"] == "satisfied"
    assert task14["missing"] == []


def test_final_runtime_validation_runs_local_repo_checks_without_harness() -> None:
    report = final_runtime_validation(
        MANIFEST_PATH,
        addon_config_path=ADDON_CONFIG,
        ha_harness=None,
        addon_image="local/homewakeword",
    )
    validation = cast(dict[str, Any], report["validation"])

    assert report["verdict"] == "pass"
    assert validation["self_test_status"] == "ok"
    assert validation["positive_replay_exit"] == 0
    assert validation["negative_replay_exit"] == 0
    assert validation["ha_smoke_verdict"] is None
    assert cast(dict[str, Any], report["ha_harness"])["executed"] is False


def test_final_runtime_validation_integrates_ha_smoke_when_harness_is_provided() -> (
    None
):
    fake_ha_report = {
        "verdict": "blocked",
        "subsystems": {
            "ha_harness": {
                "status": "blocked",
                "code": "HA_HARNESS_BOOT_BLOCKED",
                "detail": "port 8123 is already allocated",
            }
        },
    }

    with patch(
        "scripts.final_runtime_validation.ha_smoke", return_value=fake_ha_report
    ) as mocked_ha_smoke:
        report = final_runtime_validation(
            MANIFEST_PATH,
            addon_config_path=ADDON_CONFIG,
            ha_harness=REPO_ROOT
            / "tests"
            / "harness"
            / "ha-supervised"
            / "docker-compose.yml",
            addon_image="local/homewakeword",
        )

    validation = cast(dict[str, Any], report["validation"])
    ha_harness = cast(dict[str, Any], report["ha_harness"])

    assert mocked_ha_smoke.called
    assert report["verdict"] == "blocked"
    assert validation["ha_smoke_verdict"] == "blocked"
    assert ha_harness["executed"] is True
    assert ha_harness["status"] == "blocked"
    assert ha_harness["code"] == "HA_HARNESS_BOOT_BLOCKED"
    assert "port 8123" in ha_harness["detail"]
    assert any(
        "HA_HARNESS_BOOT_BLOCKED" in limitation
        for limitation in cast(list[str], report["limitations"])
    )
