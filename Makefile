PY ?= laris-env/bin/python

.PHONY: lint typecheck docs test check clean

lint:
	$(PY) -m ruff check .

typecheck:
	$(PY) -m mypy src

docs:
	$(PY) scripts/validate_docs.py

test:
	$(PY) -m pytest -p no:cacheprovider

check: lint typecheck docs test

clean:
	find . -name __pycache__ -not -path './laris-env/*' -prune -exec rm -rf {} +
	rm -rf .mypy_cache .ruff_cache .pytest_cache src/laris.egg-info
