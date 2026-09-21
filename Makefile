# Strategy Navigator — dev tasks
.DEFAULT_GOAL := help
SHELL := /bin/bash

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Create venv and install (dev extras)
	uv venv && uv pip install -e ".[dev]"

prompts-pull: ## Export stage prompts from the n8n MongoDB into prompts/_mongo/
	uv run strategy-navigator prompts pull

prompts-audit: ## Show every prompt ref, its n8n source, and what resolves at runtime
	uv run strategy-navigator prompts audit

fmt: ## Format + autofix
	uv run ruff format . && uv run ruff check --fix .

lint: ## Lint + typecheck
	uv run ruff check . && uv run mypy src

test: ## Run unit tests
	uv run pytest

test-int: ## Run integration tests (needs Postgres + LiteLLM up)
	uv run pytest -m integration

migrate: ## Apply DB migrations (app tables) + install procrastinate schema
	uv run strategy-navigator db upgrade

serve: ## Run the API (reload)
	uv run strategy-navigator serve --reload

worker-short: ## Run the SHORT lane worker
	uv run strategy-navigator worker --lane short

worker-long: ## Run the LONG lane worker
	uv run strategy-navigator worker --lane long

worker-retry: ## Run the RETRY lane worker
	uv run strategy-navigator worker --lane retry

up: ## Start local infra (Postgres + LiteLLM) and the full app
	docker compose up -d --build

down: ## Stop local infra
	docker compose down

logs: ## Tail app logs
	docker compose logs -f api worker-short worker-long worker-retry

eval: ## Run stage quality evals
	uv run python evals/run_evals.py

.PHONY: help install prompts-pull prompts-audit fmt lint test test-int migrate serve worker-short worker-long worker-retry up down logs eval
