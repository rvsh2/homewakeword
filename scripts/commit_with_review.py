from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys

from scripts.validate_repo import REQUIRED_REVIEW_SECTIONS


REVIEW_ARTIFACT_MARKER = "<!-- homewake-review-artifact -->"


class ReviewValidationError(ValueError):
    """Raised when a review artifact is missing or invalid."""


class CommitWithReviewError(ValueError):
    """Raised when commit execution cannot proceed."""


@dataclass(frozen=True, slots=True)
class ReviewArtifact:
    task_number: int
    title: str
    path: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.commit_with_review")
    parser.add_argument("--task", type=int, required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser


def validate_review_artifact(review_path: Path, task_number: int) -> ReviewArtifact:
    if not review_path.exists():
        raise ReviewValidationError(
            "review artifact does not exist; run python -m scripts.generate_review first"
        )
    content = review_path.read_text(encoding="utf-8")
    if REVIEW_ARTIFACT_MARKER not in content:
        raise ReviewValidationError("review artifact marker is missing")
    task_match = re.search(r"<!-- task: (?P<task>\d+) -->", content)
    title_match = re.search(r"<!-- title: (?P<title>.+?) -->", content)
    if task_match is None or title_match is None:
        raise ReviewValidationError("review artifact metadata is incomplete")
    artifact_task = int(task_match.group("task"))
    if artifact_task != task_number:
        raise ReviewValidationError(
            f"review artifact task mismatch: expected {task_number}, found {artifact_task}"
        )
    lowered = content.lower()
    for section in REQUIRED_REVIEW_SECTIONS:
        if f"## {section}" not in lowered:
            raise ReviewValidationError(
                f"review artifact is missing section: {section}"
            )
    if "- Tests:" not in content or "- Notes:" not in content:
        raise ReviewValidationError(
            "review artifact must include tests and notes lines"
        )
    return ReviewArtifact(
        task_number=artifact_task,
        title=title_match.group("title").strip(),
        path=review_path,
    )


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )


def commit_with_review(
    task_number: int,
    message: str,
    review_path: Path,
    repo_root: Path,
    *,
    dry_run: bool = False,
) -> str:
    if task_number <= 0:
        raise CommitWithReviewError("task number must be positive")
    if not message.strip():
        raise CommitWithReviewError("commit message must be a non-empty string")
    artifact = validate_review_artifact(review_path, task_number)
    if dry_run:
        return (
            f"review validated for dry-run commit: task={artifact.task_number} "
            f"title={artifact.title} review={artifact.path}"
        )

    repo_check = _run_git(repo_root, "rev-parse", "--show-toplevel")
    if repo_check.returncode != 0:
        raise CommitWithReviewError("git repository not available for commit execution")
    staged_check = _run_git(repo_root, "diff", "--cached", "--quiet")
    if staged_check.returncode == 0:
        raise CommitWithReviewError(
            "no staged changes found; stage changes before commit"
        )
    if staged_check.returncode not in {0, 1}:
        raise CommitWithReviewError(
            staged_check.stderr.strip() or "git staged diff check failed"
        )
    commit_result = _run_git(repo_root, "commit", "-m", message.strip())
    if commit_result.returncode != 0:
        raise CommitWithReviewError(
            commit_result.stderr.strip()
            or commit_result.stdout.strip()
            or "git commit failed"
        )
    return (
        f"commit created with validated review: task={artifact.task_number} "
        f"title={artifact.title}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(
            commit_with_review(
                args.task,
                args.message,
                args.review,
                args.repo_root,
                dry_run=args.dry_run,
            )
        )
    except (ReviewValidationError, CommitWithReviewError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
