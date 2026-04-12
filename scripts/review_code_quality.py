from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


TASK14_FILES = [
    "README.md",
    "docs/development.md",
    "docs/release.md",
    "scripts/generate_review.py",
    "scripts/commit_with_review.py",
    "scripts/release_dry_run.py",
    "scripts/verify_plan_compliance.py",
    "scripts/review_code_quality.py",
    "scripts/final_runtime_validation.py",
    "scripts/check_scope_fidelity.py",
]

NOTE_MARKER = "TO" + "DO"
REPAIR_MARKER = "FIX" + "ME"
MARKER_WARNING_LABEL = NOTE_MARKER + "/" + REPAIR_MARKER


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.review_code_quality")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--pytest-report", type=Path, default=None)
    parser.add_argument("--soak-report", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _python_files(repo_root: Path) -> list[Path]:
    return [
        repo_root / rel_path for rel_path in TASK14_FILES if rel_path.endswith(".py")
    ]


def review_code_quality(
    repo_root: Path,
    *,
    pytest_report: Path | None,
    soak_report: Path | None,
) -> dict[str, object]:
    failures: list[str] = []
    warnings: list[str] = []
    for rel_path in TASK14_FILES:
        if not (repo_root / rel_path).exists():
            failures.append(f"missing required task-14 file: {rel_path}")
    for path in _python_files(repo_root):
        source = path.read_text(encoding="utf-8")
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            failures.append(f"syntax error in {path}: {exc}")
        if NOTE_MARKER in source or REPAIR_MARKER in source:
            warnings.append(f"leftover {MARKER_WARNING_LABEL} marker in {path}")
    if pytest_report is not None and not pytest_report.exists():
        failures.append(f"pytest report does not exist: {pytest_report}")
    if soak_report is not None and not soak_report.exists():
        failures.append(f"soak report does not exist: {soak_report}")
    if pytest_report is None:
        warnings.append("pytest report not provided to code quality review")
    if soak_report is None:
        warnings.append("soak report not provided to code quality review")
    return {
        "repo_root": str(repo_root),
        "checked_files": TASK14_FILES,
        "failures": failures,
        "warnings": warnings,
        "verdict": "pass" if not failures else "fail",
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = review_code_quality(
        args.repo_root,
        pytest_report=args.pytest_report,
        soak_report=args.soak_report,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"code quality review written: verdict={report['verdict']} output={args.output}"
    )
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
