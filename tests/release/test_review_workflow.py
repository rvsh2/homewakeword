from __future__ import annotations

from pathlib import Path

from scripts.commit_with_review import main as commit_with_review_main
from scripts.generate_review import generate_review


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_PATH = REPO_ROOT / ".sisyphus" / "plans" / "implementation-plan.md"


def test_generate_review_writes_required_review_artifact(tmp_path: Path) -> None:
    output_path = tmp_path / "commit-14.md"

    message = generate_review(
        14,
        "python -m pytest tests/docs tests/release -q",
        "task-14 workflow coverage",
        output_path,
        plan_path=PLAN_PATH,
    )

    content = output_path.read_text(encoding="utf-8")
    assert "review artifact generated" in message
    assert "<!-- homewakeword-review-artifact -->" in content
    assert "<!-- task: 14 -->" in content
    assert (
        "Finalize developer docs, release workflow, and commit discipline automation"
        in content
    )
    assert "## scope drift" in content
    assert "## diff sanity" in content


def test_commit_with_review_blocks_missing_review_artifact(capsys) -> None:
    exit_code = commit_with_review_main(
        [
            "--task",
            "14",
            "--message",
            "docs(release): finalize workflows and commit review automation",
            "--review",
            ".sisyphus/evidence/reviews/commit-14.md",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "run python -m scripts.generate_review first" in captured.err


def test_commit_with_review_uses_existing_artifact_in_dry_run(tmp_path: Path) -> None:
    review_path = tmp_path / "commit-14.md"
    generate_review(
        14,
        "python -m pytest tests/docs tests/release -q",
        "task-14 workflow coverage",
        review_path,
        plan_path=PLAN_PATH,
    )

    exit_code = commit_with_review_main(
        [
            "--task",
            "14",
            "--message",
            "docs(release): finalize workflows and commit review automation",
            "--review",
            str(review_path),
            "--dry-run",
        ]
    )

    assert exit_code == 0
