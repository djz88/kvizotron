# Vygenerováno heimdallem. Cíl quality je jediný zdroj pravdy pro CI: CI má volat
# `make quality`, ne vlastní příkazy. `make lint fix` spustí lint s opravami (příkaz
# lintu k tomu používá $(LINT_FIX), pokud nástroj opravy umí).
.DEFAULT_GOAL := help
LINT_FIX := $(if $(filter fix,$(MAKECMDGOALS)),--fix)
.PHONY: help setup lint test secrets quality smoke hooks fix messages

help: ## Vypíše cíle
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/^([a-zA-Z_-]+):[^#]*## (.*)$$/  \1  \2/'

setup: ## Nainstaluje závislosti
	uv sync --frozen

lint: ## Lint (make lint fix = s opravami)
	uv run ruff check $(LINT_FIX) .
	uv run ruff format $(if $(LINT_FIX),,--check) .
	uv run mypy

fix: ; @:

test: ## Testy
	uv run pytest

# Běží na Pythonu 3.14: pre-commit potřebuje PyYAML, který pro 3.15 nemá wheel.
secrets: ## Hledá tajné údaje (gitleaks) ve staged změnách a v historii gitu
	uvx --python 3.14 pre-commit@4.7.0 run --all-files
	uvx --python 3.14 pre-commit@4.7.0 run --all-files --hook-stage manual gitleaks-history

quality: lint test secrets ## Lint, testy a gitleaks (to samé běží v CI)

smoke: ## Ověří nasazení: Docker Compose, Caddy, zdraví aplikace
	sh deploy/smoke.sh

messages: ## Vytáhne texty k překladu a zkompiluje katalogy (locale/)
	uv run python -m tools.messages

hooks: ## Nainstaluje git hooky
	pre-commit install
