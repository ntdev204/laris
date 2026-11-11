PY ?= laris-env/bin/python

.PHONY: lint typecheck docs workflow test test-no-training check check-no-training clean

lint:
	$(PY) -m ruff check .

typecheck:
	$(PY) -m mypy src

docs:
	$(PY) scripts/validate_docs.py

# Explicit preparation allowlist: none of these tests trains/fits or invokes optimization.
test-no-training:
	$(PY) -m pytest -p no:cacheprovider tests/documentation \
		tests/contract/test_training_readiness_contracts.py \
		tests/unit/language/test_readiness.py tests/cli/test_owner_runbook.py

check-no-training: lint typecheck docs test-no-training

test:
	$(PY) -m pytest -p no:cacheprovider

check: lint typecheck docs test

clean:
	find . -name __pycache__ -not -path './laris-env/*' -prune -exec rm -rf {} +
	rm -rf .mypy_cache .ruff_cache .pytest_cache src/laris.egg-info src/*.egg-info
