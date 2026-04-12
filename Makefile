.PHONY: verify test verify-addon addon-image addon-self-test

verify:
	python -m pytest -q
	python -m scripts.validate_repo
	python -m scripts.validate_addon_config --config addon/homewake-bcresnet/config.yaml --options tests/fixtures/addon/options.valid.json

test:
	python -m pytest -q

verify-addon:
	python -m scripts.validate_addon_config --config addon/homewake-bcresnet/config.yaml --options tests/fixtures/addon/options.valid.json

addon-image:
	docker build -f addon/homewake-bcresnet/Dockerfile -t local/homewake-bcresnet .

addon-self-test: addon-image
	docker run --rm local/homewake-bcresnet --self-test --report /tmp/self-test.json
