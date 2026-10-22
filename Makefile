# Common developer tasks (roadmap #73).
PYTHON ?= python3

.PHONY: help install test lint format ci run clean
help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

install:  ## Create .venv and install editable with dev extras
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

test:  ## Run the full test suite
	$(PYTHON) -m unittest discover -s tests

lint:  ## Ruff lint + format check
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:  ## Apply ruff fixes and formatting
	$(PYTHON) -m ruff check --fix .
	$(PYTHON) -m ruff format .

ci:  ## All three local gates (what CI runs)
	$(PYTHON) local_ci.py

run:  ## Launch the desktop app
	$(PYTHON) -m neezy_app

clean:  ## Remove caches and build artifacts
	rm -rf build dist *.egg-info .ruff_cache .pytest_cache
	find . -name __pycache__ -type d -exec rm -rf {} +
