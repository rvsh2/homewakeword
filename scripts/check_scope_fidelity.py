from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


FORBIDDEN_PATTERNS = {
    r"drop-in compatibility": "unsupported drop-in compatibility claim",
    r"full compatibility with openwakeword": "unsupported full compatibility claim",
    r"run unchanged on bc-?resnet": "unsupported unchanged-model claim",
    r"openwakeword .*\.tflite.* unchanged": "unsupported unchanged openWakeWord artifact claim",
}
SCANNED_PATHS = [
    "README.md",
    "docs/development.md",
    "docs/release.md",
    "scripts/commit_with_review.py",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.check_scope_fidelity")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def check_scope_fidelity(plan_path: Path, repo_root: Path) -> dict[str, object]:
    issues: list[str] = []
    del plan_path
    for rel_path in SCANNED_PATHS:
        path = repo_root / rel_path
        if not path.exists():
            issues.append(f"missing scope-reviewed path: {rel_path}")
            continue
        content = path.read_text(encoding="utf-8")
        for pattern, reason in FORBIDDEN_PATTERNS.items():
            if re.search(pattern, content, flags=re.IGNORECASE):
                issues.append(f"{reason} in {rel_path}")
    commit_script = (repo_root / "scripts" / "commit_with_review.py").read_text(
        encoding="utf-8"
    )
    if re.search(r"from\s+scripts\.generate_review\s+import", commit_script):
        issues.append("commit_with_review imports generate_review directly")
    if re.search(r"import\s+scripts\.generate_review", commit_script):
        issues.append("commit_with_review imports scripts.generate_review directly")
    return {
        "repo_root": str(repo_root),
        "scanned_paths": SCANNED_PATHS,
        "issues": issues,
        "verdict": "pass" if not issues else "fail",
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = check_scope_fidelity(args.plan, args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"scope fidelity report written: verdict={report['verdict']} output={args.output}"
    )
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
