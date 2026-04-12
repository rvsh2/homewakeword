# Release and review workflow

## Non-destructive release dry-run

Use the dry-run entrypoint to validate manifests, startup, release metadata, and self-test behavior without publishing images or pushing releases:

```bash
python -m scripts.release_dry_run
```

The generated report summarizes:

- approved model artifacts that would be included in a private release
- the add-on image template and local dry-run image tag
- startup/release/self-test validation results
- environment limitations such as the missing official Home Assistant builder tool

Dry-run mode never publishes OCI images, GitHub releases, or other release assets.

## Two-step short review gate

The planned autonomous review flow is intentionally split into two commands.

### 1. Generate the review artifact

```bash
python -m scripts.generate_review --task 14 --tests "python -m pytest tests/docs tests/release -q && python -m scripts.release_dry_run" --notes "docs and dry-run automation" --output .sisyphus/evidence/reviews/commit-14.md
```

This writes the review artifact and captures the checklist headings from `.github/PRE_COMMIT_REVIEW.md`.

### 2. Commit only with an existing review artifact

```bash
python -m scripts.commit_with_review --task 14 --message "docs(release): finalize workflows and commit review automation" --review .sisyphus/evidence/reviews/commit-14.md
```

`commit_with_review` validates the supplied artifact and only then attempts the commit. It does **not** auto-create missing review artifacts.

## Final-gate entrypoints

The task-14 final gate surfaces are local repo automation entrypoints:

```bash
python -m scripts.verify_plan_compliance --help
python -m scripts.review_code_quality --help
python -m scripts.final_runtime_validation --help
python -m scripts.check_scope_fidelity --help
```

Their purpose is to summarize repo-local evidence and catch plan drift, code quality regressions, runtime validation gaps, or unsupported compatibility claims before a real release candidate is treated as done.

## CI and Makefile wiring

Task-14 wiring is exposed through:

- `make verify-task14`
- `.github/workflows/ci.yml`

CI runs the docs/release pytest suite, the release dry-run, and the `--help` checks for the review and final-gate scripts.
