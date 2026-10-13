.PHONY: help install check lint format test test-v mypy check-all clean run

help: ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install dependencies using uv
	uv sync

lint: ## Run linter (ruff)
	uv run ruff check .

format: ## Format code (ruff format and autofix)
	uv run ruff check --fix .
	uv run ruff format .

check: ## Check code style without modifying files
	uv run ruff check .
	uv run ruff format --check .

mypy: ## Run type checker (mypy)
	uv run mypy src tests scripts

test: ## Run tests (pytest)
	uv run pytest

test-v: ## Run tests with verbose output
	uv run pytest -v

check-all: check mypy test ## Run all checks (format check, lint, mypy, pytest)

clean: ## Clean up caches and temporary build artifacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	find . -type d -name "__pycache__" -exec rm -rf {} +

run: ## Run cache-mcp server CLI (over stdio)
	uv run python -m cache_mcp.main

release: ## Run release script (e.g. make release VER=0.2.0 or make release VER=0.2.0 ARGS=--dry-run)
	@if [ -z "$(VER)" ]; then echo "Error: VER is required. Usage: make release VER=0.2.0 [ARGS=--dry-run]" && exit 1; fi
	uv run python scripts/release.py $(VER) $(ARGS)
