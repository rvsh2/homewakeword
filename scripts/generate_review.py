from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import re

from scripts.validate_repo import REQUIRED_REVIEW_SECTIONS


REVIEW_ARTIFACT_MARKER = "<!-- homewake-review-artifact -->"
DEFAULT_PLAN_PATH = (
    Path(__file__).resolve().parents[1]
    / ".sisyphus"
    / "plans"
    / "implementation-plan.md"
)


class ReviewGenerationError(ValueError):
    """Raised when a review artifact cannot be generated."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.generate_review")
    parser.add_argument("--task", type=int, required=True)
    parser.add_argument("--tests", required=True)
    parser.add_argument("--notes", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    return parser


def resolve_task_title(plan_path: Path, task_number: int) -> str:
    pattern = re.compile(rf"^- \[[ x]\] {task_number}\. (?P<title>.+)$")
    for line in plan_path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match is not None:
            return match.group("title").strip()
    raise ReviewGenerationError(
        f"task {task_number} was not found in plan: {plan_path}"
    )


def render_review_artifact(
    *,
    task_number: int,
    task_title: str,
    tests: str,
    notes: str,
    output_path: Path,
    plan_path: Path,
) -> str:
    generated_at = datetime.now(timezone.utc).isoformat()
    lines = [
        f"# Task {task_number} short review",
        "",
        REVIEW_ARTIFACT_MARKER,
        f"<!-- task: {task_number} -->",
        f"<!-- title: {task_title} -->",
        "",
        f"- Task: {task_number}",
        f"- Title: {task_title}",
        f"- Tests: {tests}",
        f"- Notes: {notes}",
        f"- Generated At (UTC): {generated_at}",
        f"- Plan: {plan_path}",
        f"- Output: {output_path}",
    ]
    for section in REQUIRED_REVIEW_SECTIONS:
        lines.extend(
            [
                "",
                f"## {section}",
                f"- Task context: {task_title}",
                f"- Evidence/tests: {tests}",
                f"- Notes: {notes}",
            ]
        )
    return "\n".join(lines) + "\n"


def generate_review(
    task_number: int,
    tests: str,
    notes: str,
    output_path: Path,
    plan_path: Path = DEFAULT_PLAN_PATH,
) -> str:
    if task_number <= 0:
        raise ReviewGenerationError("task number must be positive")
    if not tests.strip():
        raise ReviewGenerationError("tests must be a non-empty string")
    if not notes.strip():
        raise ReviewGenerationError("notes must be a non-empty string")
    task_title = resolve_task_title(plan_path, task_number)
    artifact = render_review_artifact(
        task_number=task_number,
        task_title=task_title,
        tests=tests.strip(),
        notes=notes.strip(),
        output_path=output_path,
        plan_path=plan_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(artifact, encoding="utf-8")
    return f"review artifact generated: task={task_number} title={task_title} output={output_path}"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(
            generate_review(
                args.task,
                args.tests,
                args.notes,
                args.output,
                plan_path=args.plan,
            )
        )
    except (ReviewGenerationError, OSError) as exc:
        print(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
