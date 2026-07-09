SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

RUN_ID ?= local
RUNS_ROOT ?= runs
REPORT_DIR ?= $(RUNS_ROOT)/$(RUN_ID)
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
		'run-smoke        execute example scenario and write evidence' \
		'e2e              resolve scenario and execute run' \
		'status/logs/stop lifecycle commands for a run id'

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
	ROBOTICS_RUNS_ROOT="$(RUNS_ROOT)" ROBOTICS_SKIP_ROS_OBSERVER=1 \
	robotics-harness run \
		--scenario "$(RESOLVED_SCENARIO)" \
		--evidence "$(EVIDENCE)" \
		--run-id "$(RUN_ID)"
	python -c "import json,sys; d=json.load(open('$(EVIDENCE)', encoding='utf-8')); assert any(c['name']=='process_execution' and c['result']=='executed' for c in d['checks'])"

e2e: run-smoke
	python -m json.tool "$(RESOLVED_SCENARIO)" > /dev/null
	python -m json.tool "$(RESOLUTION_TRACE)" > /dev/null
	python -m json.tool "$(EVIDENCE)" > /dev/null

status:
	robotics-harness status --run-id "$(RUN_ID)"

logs:
	robotics-harness logs --run-id "$(RUN_ID)" --tail 80

stop:
	robotics-harness stop --run-id "$(RUN_ID)"

pre-commit:
	pre-commit run --all-files

ci: validate lint test e2e

clean:
	rm -rf artifacts runs .pytest_cache .ruff_cache
