PY ?= laris-env/bin/python

.PHONY: bench-vault lint typecheck docs workflow test test-no-training test-model-free eval-fast check check-no-training clean

lint:
	$(PY) -m ruff check .

typecheck:
	$(PY) -m mypy src

docs:
	$(PY) scripts/validate_docs.py

spec:
	$(PY) scripts/validate_spec.py

# Explicit preparation allowlist: none of these tests trains/fits or invokes optimization.
test-no-training:
	$(PY) -m pytest -p no:cacheprovider tests/documentation \
		tests/contract/test_training_readiness_contracts.py tests/contract/test_spec_ledger.py \
		tests/unit/language/test_readiness.py tests/cli/test_owner_runbook.py

# Vault, brain, scholarly analytics, server and security suites. None trains or fits anything.
test-model-free:
	$(PY) -m pytest -p no:cacheprovider tests/unit/vault tests/unit/scholarly tests/unit/security \
		tests/unit/gateway tests/unit/serverdata tests/unit/architecture \
		tests/unit/evaluation/test_model_free_suite.py tests/unit/cli/test_tls_init.py \
		tests/unit/cli/test_server_url_in_settings.py tests/unit/cli/test_server_auth.py

# Vault at 10,000 notes against the spec targets and recorded budgets (run on the workstation).
bench-vault:
	$(PY) scripts/benchmark_vault.py --notes 10000 --check

# The quick model-free evaluation suites (retrieval, citation, injection, vault round-trip).
eval-fast:
	$(PY) -m cli.server evaluate suite --fast

check-no-training: lint typecheck docs spec test-no-training test-model-free eval-fast

test:
	$(PY) -m pytest -p no:cacheprovider

check: lint typecheck docs test

clean:
	find . -name __pycache__ -not -path './laris-env/*' -prune -exec rm -rf {} +
	rm -rf .mypy_cache .ruff_cache .pytest_cache src/laris.egg-info src/*.egg-info
