PYTHON ?= python3
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
TEST_PYTHON ?= $(VENV_PYTHON)
E2E_BASETEMP ?= .tmp/uart-vrf-e2e
E2E_RESULTS ?= host-e2e-results

.PHONY: test-setup test-fast test-e2e test

test-setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install -r tests/requirements-e2e.txt

test-fast:
	$(TEST_PYTHON) -m pytest tests/e2e -m "not host_e2e" -vv --tb=long

test-e2e:
	mkdir -p $(E2E_RESULTS)
	$(TEST_PYTHON) -m pytest tests/e2e -m host_e2e -vv --tb=long --durations=20 \
		--basetemp="$(E2E_BASETEMP)" \
		--junitxml="$(E2E_RESULTS)/junit.xml"

test: test-fast test-e2e
