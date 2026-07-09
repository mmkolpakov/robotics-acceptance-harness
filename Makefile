SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

REPORT_DIR ?= artifacts/reports
JUNIT_XML ?= $(REPORT_DIR)/results.xml

.PHONY: help quickstart doctor validate lint test example-hydra example-launch-testing pre-commit ci clean

help:
	@printf '%s\n' \
		'quickstart           install tools and run ci' \
		'doctor               print tool versions' \
		'validate             yamllint' \
		'lint                 ruff' \
		'test                 run the plugin unit/integration tests' \
		'example-hydra        run the Hydra-composed-scenario example' \
		'example-launch-testing  run the launch_testing_ros example (needs ROS 2 Jazzy)' \
		'ci                   run validate, lint, test, junitxml'

quickstart:
	python -m pip install --disable-pip-version-check -e . -r requirements-dev.txt
	$(MAKE) ci

doctor:
	python --version
	python -m pytest --version

validate:
	yamllint .

lint:
	ruff check .

test:
	mkdir -p "$(REPORT_DIR)"
	python -m pytest --junitxml="$(JUNIT_XML)"

example-hydra:
	python -m pip install --disable-pip-version-check -r examples/hydra/requirements.txt
	cd examples/hydra && python -m pytest -q test_guard_with_hydra.py
	cd examples/hydra && python -m pytest -q test_guard_with_hydra.py --robotics-allow-physical-actuation

example-launch-testing:
	python -m pytest -q examples/launch_testing/test_clock_graph_ready.py

pre-commit:
	pre-commit run --all-files

ci: validate lint test

clean:
	rm -rf artifacts .pytest_cache .ruff_cache
