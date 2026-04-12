# HomeWake BC-ResNet

Private Home Assistant add-on repository for the HomeWake BC-ResNet wake word runtime.

## Main developer entrypoints

- Local development and fixture replay: [`docs/development.md`](docs/development.md)
- Release dry-run and review/commit workflow: [`docs/release.md`](docs/release.md)

## Quick start

Install the package in editable mode and run the baseline checks:

```bash
python -m pip install -e .
make test
make verify
make verify-task14
```

## Core workflows

### Fixture replay

Use fixture replay to validate the packaged wake-word manifests without touching live audio devices:

```bash
python -m scripts.replay_stream --manifest models/manifest.yaml --wake-word okay_nabu --input tests/fixtures/stream/okay_nabu_positive.wav --expect okay_nabu --json-out .sisyphus/evidence/task-runtime-ok-nabu.json
```

### Add-on build and local self-test

Validate the add-on metadata, then build and self-test the local container image:

```bash
python -m scripts.validate_addon_config --config addon/homewake-bcresnet/config.yaml --options tests/fixtures/addon/options.valid.json
make addon-image
make addon-self-test
```

### Artifact policy

Runtime metadata lives in `models/manifest.yaml`, but model weights are not committed as general-purpose release blobs. The repository uses manifest metadata, OCI labels, and release-dry-run reporting to describe what would ship while keeping publish steps non-destructive in local automation.

### Custom model workflow

Train or export a bundle with `python -m scripts.train_custom`, then place validated bundles under `/share/homewake/models` for runtime import. Optional `/share/openwakeword` compatibility scanning stays disabled unless explicitly enabled.

### Autonomous short review before commit

The repo keeps the planned two-step review gate:

1. `python -m scripts.generate_review ...` writes the review artifact.
2. `python -m scripts.commit_with_review ...` validates and uses an existing artifact; it never auto-generates one.

See [`docs/release.md`](docs/release.md) for the full dry-run and final-gate workflow.
