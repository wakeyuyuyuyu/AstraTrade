PYTHON ?= python3
VENV ?= .venv
PORT ?= 8787

VENV_PYTHON := $(VENV)/bin/python
VENV_PIP := $(VENV)/bin/pip

.PHONY: setup init dashboard run scheduler manual style check clean

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PIP) install -r requirements.txt
	test -f .env || cp .env.example .env
	test -f workspace/state/account_state.json && test -f workspace/pools/candidates.jsonl || bash initialization.sh
	$(VENV_PYTHON) -m runtime.investment_style
	@echo "Setup complete. Edit .env, then run: make dashboard"

init:
	bash initialization.sh

dashboard:
	STOCK_AGENT_PYTHON="$(VENV_PYTHON)" $(VENV_PYTHON) dashboard/server.py $(PORT)

run:
	$(VENV_PYTHON) -m runtime.launcher --mode scheduler

scheduler:
	$(VENV_PYTHON) -m runtime.scheduler

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
