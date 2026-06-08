PYTHON ?= python3.11
VENV ?= .venv
PORT ?= 8787

VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip
PYTHON311_CHECK := import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)

.PHONY: setup init dashboard run scheduler manual style check clean

setup:
	@PYTHON_BIN="$$(bash scripts/ensure_python311.sh "$(PYTHON)")"; \
	echo "Using Python $$("$$PYTHON_BIN" -c 'import sys; print(sys.version.split()[0])') at $$PYTHON_BIN"; \
	if [ -x "$(VENV_PYTHON)" ] && ! "$(VENV_PYTHON)" -c '$(PYTHON311_CHECK)' >/dev/null 2>&1; then \
		echo "Existing $(VENV) is not Python 3.11; recreating it."; \
		rm -rf "$(VENV)"; \
	fi; \
	"$$PYTHON_BIN" -m venv "$(VENV)"; \
	"$(VENV_PYTHON)" -m pip install --upgrade pip; \
	"$(VENV_PIP)" install -r requirements.txt; \
	test -f .env || cp .env.example .env; \
	test -f workspace/state/account_state.json && test -f workspace/pools/candidates.jsonl || bash initialization.sh; \
	"$(VENV_PYTHON)" -m runtime.investment_style; \
	echo "Setup complete. Edit .env, then run: make dashboard"

init:
	bash initialization.sh

dashboard:
	STOCK_AGENT_PYTHON="$(VENV_PYTHON)" $(VENV_PYTHON) dashboard/server.py $(PORT)

run:
	$(VENV_PYTHON) -m runtime.launcher --mode scheduler

scheduler:
	$(VENV_PYTHON) -m runtime.agent

manual:
	@test -n "$(TASK)" || (echo 'Usage: make manual TASK="check current holdings"'; exit 1)
	$(VENV_PYTHON) -m runtime.launcher --task "$(TASK)"

style:
	$(VENV_PYTHON) -m runtime.investment_style

check:
	$(VENV_PYTHON) -m py_compile services/*.py runtime/*.py tools/*.py dashboard/server.py subagent/holding_follow/*.py subagent/candidate_follow/*.py
	@echo "Python compile check passed."

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.pyc' -delete
