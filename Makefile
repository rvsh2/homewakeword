.PHONY: verify test

verify:
	python -m pytest -q
	python -m scripts.validate_repo

test:
	python -m pytest -q
