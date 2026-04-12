from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from scripts.check_scope_fidelity import check_scope_fidelity
from scripts.final_runtime_validation import final_runtime_validation
from scripts.review_code_quality import review_code_quality
from scripts.verify_plan_compliance import audit_plan_compliance


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / ".sisyphus" / "plans" / "implementation-plan.md"
EVIDENCE_ROOT = REPO_ROOT / ".sisyphus" / "evidence"
MANIFEST_PATH = REPO_ROOT / "models" / "manifest.yaml"
ADDON_CONFIG = REPO_ROOT / "addon" / "homewake-bcresnet" / "config.yaml"


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
        addon_image="local/homewake-bcresnet",
    )
    validation = cast(dict[str, Any], report["validation"])

    assert report["verdict"] == "pass"
    assert validation["self_test_status"] == "ok"
    assert validation["positive_replay_exit"] == 0
    assert validation["negative_replay_exit"] == 0
