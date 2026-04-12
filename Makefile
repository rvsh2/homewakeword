.PHONY: verify test verify-addon addon-image addon-self-test addon-builder-test verify-task12 verify-task14 verify-e2e release-dry-run final-gates-help

verify:
	python -m pytest -q
	$(MAKE) verify-task12
	python -m scripts.validate_repo
	python -m scripts.validate_addon_config --config addon/homewakeword-bcresnet/config.yaml --options tests/fixtures/addon/options.valid.json
	$(MAKE) verify-task14

test:
	python -m pytest -q

verify-addon:
	python -m scripts.validate_addon_config --config addon/homewakeword-bcresnet/config.yaml --options tests/fixtures/addon/options.valid.json

addon-image:
	docker build -f addon/homewakeword-bcresnet/Dockerfile -t local/homewakeword .

addon-self-test: addon-image
	docker run --rm local/homewakeword --self-test --report /tmp/self-test.json

addon-builder-test:
	docker run --rm --privileged -v "/opt/homewake/addon/homewakeword-bcresnet:/data" -v /var/run/docker.sock:/var/run/docker.sock:ro ghcr.io/home-assistant/amd64-builder:latest --target /data --amd64 --test --image local/homewakeword-{arch} --docker-hub local

verify-task12:
	python -m pytest tests/integration/test_restart_reload.py -q
	python -m scripts.soak_test --manifest models/manifest.yaml --input-dir tests/fixtures/soak --hours 6 --report .sisyphus/evidence/task-12-soak.json

verify-task14:
	python -m pytest tests/docs tests/release -q
	python -m scripts.release_dry_run
	$(MAKE) final-gates-help

verify-e2e:
	python -m pytest tests/e2e -q
	python -m scripts.ha_smoke --harness tests/harness/ha-supervised/docker-compose.yml --addon-slug homewakeword --addon-image local/homewakeword --wyoming-port 10400 --report .sisyphus/evidence/ha-smoke.json

release-dry-run:
	python -m scripts.release_dry_run

final-gates-help:
	python -m scripts.generate_review --help
	python -m scripts.commit_with_review --help
	python -m scripts.verify_plan_compliance --help
	python -m scripts.review_code_quality --help
	python -m scripts.final_runtime_validation --help
	python -m scripts.check_scope_fidelity --help
