SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

REPORT_DIR ?= artifacts/reports
EXAMPLE_COMPOSITION ?= examples/generic/composition.yaml
RESOLVED_SCENARIO ?= $(REPORT_DIR)/resolved-scenario.json
RESOLUTION_TRACE ?= $(REPORT_DIR)/resolution-trace.json
EVIDENCE ?= $(REPORT_DIR)/evidence-manifest.json

.PHONY: help quickstart doctor validate lint test e2e scenario-resolve run-smoke status logs stop pre-commit ci clean

help:
	@printf '%s\n' \
		'quickstart       install tools and run ci' \
		'doctor           print tool versions' \
		'scenario-resolve resolve example scenario with trace' \
		'run-smoke        create dry-run evidence from resolved scenario' \
		'e2e              resolve scenario and create evidence' \
		'status/logs/stop developer convenience commands'

quickstart:
	python -m pip install --disable-pip-version-check -e . -r requirements-dev.txt
	$(MAKE) ci

doctor:
	mkdir -p "$(REPORT_DIR)"
	python --version | tee "$(REPORT_DIR)/python-version.txt"
	robotics-harness doctor | tee "$(REPORT_DIR)/harness-doctor.txt"

validate:
	yamllint .
	python -m pytest tests/test_resolver.py tests/test_execution_guard.py

lint:
	ruff check .

test:
	python -m pytest

scenario-resolve:
	mkdir -p "$(REPORT_DIR)"
	robotics-harness scenario resolve \
		--composition "$(EXAMPLE_COMPOSITION)" \
		--output "$(RESOLVED_SCENARIO)" \
		--trace "$(RESOLUTION_TRACE)"

run-smoke: scenario-resolve
	robotics-harness run \
		--scenario "$(RESOLVED_SCENARIO)" \
		--evidence "$(EVIDENCE)" \
		--dry-run

e2e: run-smoke
	python -m json.tool "$(RESOLVED_SCENARIO)" > /dev/null
	python -m json.tool "$(RESOLUTION_TRACE)" > /dev/null
	python -m json.tool "$(EVIDENCE)" > /dev/null

status:
	robotics-harness status

logs:
	robotics-harness logs --tail 80

stop:
	robotics-harness stop

pre-commit:
	pre-commit run --all-files

ci: validate lint test e2e

clean:
	rm -rf artifacts .pytest_cache .ruff_cache
