from __future__ import annotations

from pathlib import Path
import sys


REQUIRED_PATHS = [
    "homewake",
    "addon/homewake-bcresnet",
    "addon/homewake-bcresnet/config.yaml",
    "addon/homewake-bcresnet/Dockerfile",
    "addon/homewake-bcresnet/run.sh",
    "tests",
    "tests/fixtures",
    "tests/fixtures/addon",
    "tests/docs",
    "tests/release",
    "scripts",
    "scripts/validate_addon_config.py",
    "scripts/generate_review.py",
    "scripts/commit_with_review.py",
    "scripts/release_dry_run.py",
    "scripts/verify_plan_compliance.py",
    "scripts/review_code_quality.py",
    "scripts/final_runtime_validation.py",
    "scripts/check_scope_fidelity.py",
    "models",
    "docs",
    "docs/development.md",
    "docs/release.md",
    ".github/workflows",
    ".editorconfig",
    ".gitignore",
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "Makefile",
    ".github/PRE_COMMIT_REVIEW.md",
]

REQUIRED_REVIEW_SECTIONS = [
    "scope drift",
    "correctness",
    "reliability",
    "error handling",
    "tests",
    "secrets",
    "diff sanity",
]


def validate_repo(root: Path) -> list[str]:
    errors: list[str] = []
    for rel_path in REQUIRED_PATHS:
        if not (root / rel_path).exists():
            errors.append(f"missing required path: {rel_path}")

    review_path = root / ".github/PRE_COMMIT_REVIEW.md"
    if review_path.exists():
        content = review_path.read_text(encoding="utf-8").lower()
        for section in REQUIRED_REVIEW_SECTIONS:
            if f"## {section}" not in content:
                errors.append(f"missing review section: {section}")

    return errors


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = validate_repo(root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("repository skeleton looks good")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
