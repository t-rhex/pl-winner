# pl-winner — common dev tasks
.DEFAULT_GOAL := help

PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

# Use the venv's executables when they exist, else fall back to system ones
ifneq ("$(wildcard $(BIN)/python)", "")
    PY := $(BIN)/python
    PIP := $(BIN)/pip
    PYTEST := $(BIN)/pytest
    RUFF := $(BIN)/ruff
    PL := $(BIN)/pl-winner
else
    PY := $(PYTHON)
    PIP := $(PYTHON) -m pip
    PYTEST := $(PYTHON) -m pytest
    RUFF := $(PYTHON) -m ruff
    PL := $(PYTHON) -m pl_winner.cli
endif

.PHONY: help
help:  ## Show this message
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} \
	     /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

.PHONY: venv
venv:  ## Create a fresh virtualenv at .venv
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip

.PHONY: install
install:  ## Install package in editable mode with dev + web extras
	$(PIP) install -e '.[dev,web]'

.PHONY: test
test:  ## Run the test suite
	$(PYTEST) tests -q

.PHONY: cov
cov:  ## Run tests with coverage report
	$(PYTEST) tests --cov=src --cov-report=term-missing

.PHONY: lint
lint:  ## Run ruff lint check
	$(RUFF) check src tests

.PHONY: fmt
fmt:  ## Auto-format with ruff
	$(RUFF) check src tests --fix
	$(RUFF) format src tests

.PHONY: build
build:  ## Build sdist + wheel into dist/
	$(PIP) install --quiet --upgrade build
	$(PY) -m build

.PHONY: clean
clean:  ## Remove build artifacts and caches
	rm -rf build dist *.egg-info src/*.egg-info
	find . -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage coverage.xml

.PHONY: tui
tui:  ## Launch the terminal UI
	$(PL) tui

.PHONY: web
web:  ## Launch the Streamlit web UI on :8501
	$(PL) web

.PHONY: docker-build
docker-build:  ## Build the Docker image
	docker build -t pl-winner:latest .

.PHONY: docker-run
docker-run:  ## Run the web UI in Docker (port 8501)
	docker compose up

.PHONY: deploy
deploy:  ## Deploy to Fly.io (requires flyctl + fly auth login)
	flyctl deploy --remote-only

.PHONY: deploy-status
deploy-status:  ## Show Fly.io app status + logs
	flyctl status --app pl-winner
	@echo
	flyctl logs --app pl-winner | tail -20

.PHONY: deploy-logs
deploy-logs:  ## Tail Fly.io logs
	flyctl logs --app pl-winner

.PHONY: release-check
release-check: clean build  ## Verify the build is releasable
	$(PIP) install --quiet --upgrade twine
	$(BIN)/twine check dist/*
	@echo "✓ build OK. Tag and push: git tag v$$($(PY) -c 'import tomllib; print(tomllib.load(open(\"pyproject.toml\",\"rb\"))[\"project\"][\"version\"])') && git push --tags"
