# HomeWake BC-ResNet

Private Home Assistant add-on skeleton for the BC-ResNet wake word project.

## Add-on packaging

Task 7 packages the local runtime as a Home Assistant add-on shell under `addon/homewake-bcresnet/`.
Use `python -m scripts.validate_addon_config --config addon/homewake-bcresnet/config.yaml --options tests/fixtures/addon/options.valid.json` to validate add-on options against the packaged schema.
Build and self-test the local image with `docker build -f addon/homewake-bcresnet/Dockerfile -t local/homewake-bcresnet .` and `docker run --rm local/homewake-bcresnet --self-test --report /tmp/self-test.json`.
