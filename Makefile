PYTHON ?= ./venv/bin/python
PIP ?= ./venv/bin/pip
DOCKER ?= docker
DATE ?= $(shell date +%F)
RUFF_TARGETS ?= run_safety_checks.py scripts/run_tests.py src/trading_bot/ops_checks/cli.py tests/test_auto_buy_manager.py tests/test_dependency_packaging_contract.py

.PHONY: \
	install-runtime install-dev install-research \
	check lint-all audit test test-targeted test-safety test-xdist \
	docker-runtime docker-research docker-dev-image \
	ops job after-close premarket

install-runtime:
	$(PIP) install -r requirements-base.txt
	$(PIP) install --no-deps -e .

install-dev:
	$(PIP) install -r requirements-base.txt
	$(PIP) install -r requirements-dev.txt
	$(PIP) install --no-deps -e .

install-research:
	$(PIP) install -r requirements-base.txt
	$(PIP) install -r requirements-research.txt
	$(PIP) install --no-deps -e .

check:
	$(PYTHON) -m ruff check $(RUFF_TARGETS)
	$(PYTHON) -m ruff format --check $(RUFF_TARGETS)
	$(PYTHON) run_safety_checks.py

lint-all:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

audit:
	$(PYTHON) ops_check.py config-audit
	$(PYTHON) ops_check.py architecture-surface
	$(PYTHON) ops_check.py packaged-entrypoints
	$(PYTHON) ops_check.py database-backups
	$(PYTHON) ops_check.py observability-health $(DATE)
	$(PYTHON) ops/deployment_reference_audit.py

test:
	$(PYTHON) -m pytest

test-targeted:
	$(PYTHON) scripts/run_tests.py

test-safety:
	$(PYTHON) run_safety_checks.py

test-xdist:
	$(PYTHON) -m pytest -n auto tests

docker-runtime:
	DOCKER_BUILDKIT=1 $(DOCKER) build --target runtime -t tradingbot-runtime:latest .

docker-research:
	DOCKER_BUILDKIT=1 $(DOCKER) build --target research -t tradingbot-research:latest .

docker-dev-image: docker-runtime docker-research

ops:
	test -n "$(CMD)" || (echo "CMD is required, for example: make ops CMD=config-audit" && exit 2)
	$(PYTHON) ops_check.py $(CMD)

job:
	test -n "$(JOB)" || (echo "JOB is required, for example: make job JOB=after_close_learning" && exit 2)
	test -n "$(SCRIPT)" || (echo "SCRIPT is required, for example: make job JOB=after_close_learning SCRIPT=pipeline/after_close_learning.py" && exit 2)
	$(PYTHON) scripts/job_runner.py --job-name "$(JOB)" -- $(PYTHON) $(SCRIPT)

after-close:
	$(PYTHON) scripts/job_runner.py --job-name after_close_learning -- $(PYTHON) pipeline/after_close_learning.py

premarket:
	$(PYTHON) ops_check.py premarket $(DATE)
