from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_readme_links_split_developer_docs() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/development.md" in readme
    assert "docs/release.md" in readme
    assert "scripts.generate_review" in readme
    assert "scripts.commit_with_review" in readme


def test_readme_explains_hacs_helper_without_claiming_runtime_install() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert (
        "HACS installs only the lightweight **HomeWakeWord** helper integration"
        in readme
    )
    assert (
        "HACS does **not** install, start, or manage the HomeWakeWord add-on runtime"
        in readme
    )
    assert "built-in **Wyoming** integration" in readme
    assert "host `homewakeword` and port `10700`" in readme


def test_development_doc_covers_required_local_workflows() -> None:
    content = (REPO_ROOT / "docs" / "development.md").read_text(encoding="utf-8")

    assert "Local setup" in content
    assert "Fixture replay" in content
    assert "Add-on build and test" in content
    assert "Artifact policy" in content
    assert "Custom model workflow" in content
    assert "python -m scripts.replay_stream" in content
    assert "make addon-image" in content
    assert "make addon-self-test" in content
    assert "python -m scripts.train_custom" in content
    assert "HACS helper integration workflow" in content
    assert "HACS installs only the helper integration" in content


def test_release_doc_covers_dry_run_and_two_step_review_gate() -> None:
    content = (REPO_ROOT / "docs" / "release.md").read_text(encoding="utf-8")

    assert "python -m scripts.release_dry_run" in content
    assert "python -m scripts.generate_review" in content
    assert "python -m scripts.commit_with_review" in content
    assert "does **not** auto-create missing review artifacts" in content
    assert "python -m scripts.verify_plan_compliance --help" in content
    assert "python -m scripts.review_code_quality --help" in content
    assert "python -m scripts.final_runtime_validation --help" in content
    assert "python -m scripts.check_scope_fidelity --help" in content


def test_release_doc_explains_hacs_contract_truthfully() -> None:
    content = (REPO_ROOT / "docs" / "release.md").read_text(encoding="utf-8")

    assert "HACS integration release contract" in content
    assert "ships only an onboarding/helper shim" in content
    assert (
        "add-on remains a separate install/start step for the actual runtime" in content
    )
    assert "host `homewakeword` and port `10700`" in content
