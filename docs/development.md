# Development workflow

## Local setup

```bash
python -m pip install -e .
python -m pytest -q
python -m scripts.validate_repo
```

Use `make verify` for the baseline repo gates and `make verify-task14` for the task-14 developer-docs and release-workflow checks.

## Fixture replay

Replay is the fastest way to validate detector behavior with committed fixtures instead of live microphones.

Positive replay example:

```bash
python -m scripts.replay_stream --manifest models/manifest.yaml --wake-word okay_nabu --input tests/fixtures/stream/okay_nabu_positive.wav --expect okay_nabu --json-out .sisyphus/evidence/task-runtime-ok-nabu.json
```

Negative replay example:

```bash
python -m scripts.replay_stream --manifest models/manifest.yaml --wake-word okay_nabu --input tests/fixtures/stream/okay_nabu_negative.wav --expect none --json-out .sisyphus/evidence/task-runtime-negative.json
```

## Add-on build and test

Validate the packaged add-on config first:

```bash
python -m scripts.validate_addon_config --config addon/homewakeword-bcresnet/config.yaml --options tests/fixtures/addon/options.valid.json
```

Then build and self-test the add-on image locally:

```bash
make addon-image
make addon-self-test
```

The repo can build the local Docker image, but the official Home Assistant add-on builder is still an environment limitation in this workspace. Task-14 automation records that limitation honestly instead of pretending it is solved.

## Artifact policy

- Keep artifact metadata in `models/manifest.yaml` and add-on metadata in `addon/homewakeword-bcresnet/config.yaml`.
- Treat manifests, provenance, and OCI labels as the source of truth for what would ship.
- Do not add HA-specific release secrets or credentials to docs, scripts, tests, or generated reports.
- Local release automation must stay dry-run only unless a later task explicitly adds real publish steps.

## Custom model workflow

Generate a repo-local custom bundle:

```bash
python -m scripts.train_custom --config tests/fixtures/training/custom_model.yaml --output-dir /tmp/homewakeword-custom
```

Then import it through the existing runtime/add-on paths:

- Primary import root: `/share/homewakeword/models`
- Optional compatibility root: `/share/openwakeword` when explicitly enabled

Validated bundle manifests are required. Bare `.tflite` or `.onnx` files without manifest metadata are rejected.

## Docs and release checks

Task-14 verification lives under `tests/docs/` and `tests/release/`:

```bash
python -m pytest tests/docs tests/release -q
python -m scripts.release_dry_run
```
