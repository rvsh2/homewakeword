from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, cast


TASK_PATTERN = re.compile(r"^- \[(?P<checked>[ x])\] (?P<number>\d+)\. (?P<title>.+)$")
TASK14_REQUIRED_PATHS = [
    "README.md",
    ".github/workflows/ci.yml",
    "Makefile",
    "scripts/generate_review.py",
    "scripts/commit_with_review.py",
    "scripts/release_dry_run.py",
    "scripts/verify_plan_compliance.py",
    "scripts/review_code_quality.py",
    "scripts/final_runtime_validation.py",
    "scripts/check_scope_fidelity.py",
    "tests/docs",
    "tests/release",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.verify_plan_compliance")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _load_tasks(plan_path: Path) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for line in plan_path.read_text(encoding="utf-8").splitlines():
        match = TASK_PATTERN.match(line)
        if match is None:
            continue
        tasks.append(
            {
                "number": int(match.group("number")),
                "title": match.group("title").strip(),
                "checked": match.group("checked") == "x",
            }
        )
    return tasks


def audit_plan_compliance(
    plan_path: Path,
    repo_root: Path,
    evidence_root: Path,
) -> dict[str, Any]:
    tasks = _load_tasks(plan_path)
    results: list[dict[str, object]] = []
    failures: list[str] = []
    for task in tasks:
        number = cast(int, task["number"])
        evidence = sorted(
            str(path.relative_to(repo_root))
            for path in evidence_root.glob(f"task-{number}*")
        )
        if number == 14:
            missing = [
                rel_path
                for rel_path in TASK14_REQUIRED_PATHS
                if not (repo_root / rel_path).exists()
            ]
            status = "satisfied" if not missing else "missing_deliverables"
            if missing:
                failures.extend(
                    f"task 14 missing deliverable: {path}" for path in missing
                )
            results.append(
                {
                    **task,
                    "status": status,
                    "evidence": evidence,
                    "missing": missing,
                }
            )
            continue
        status = "recorded_complete" if bool(task["checked"]) else "pending"
        if status == "pending":
            failures.append(f"task {number} remains pending in the plan")
        results.append({**task, "status": status, "evidence": evidence})
    return {
        "plan": str(plan_path),
        "repo_root": str(repo_root),
        "evidence_root": str(evidence_root),
        "tasks": results,
        "failures": failures,
        "verdict": "pass" if not failures else "fail",
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = audit_plan_compliance(args.plan, args.repo_root, args.evidence_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"plan compliance report written: verdict={report['verdict']} output={args.output}"
    )
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
