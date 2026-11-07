# Vygenerováno heimdallem. Cíl quality je jediný zdroj pravdy pro CI: CI má volat
# `make quality`, ne vlastní příkazy. `make lint fix` spustí lint s opravami (příkaz
# lintu k tomu používá $(LINT_FIX), pokud nástroj opravy umí).
.DEFAULT_GOAL := help
LINT_FIX := $(if $(filter fix,$(MAKECMDGOALS)),--fix)
WT_DIR := .worktrees
WT_NAME = $(or $(name),$(word 2,$(MAKECMDGOALS)))
export WT_NAME
TECH_DEBT := python3 tools/tech_debt.py --doc docs/_architecture/TECH_DEBT.md
.PHONY: help setup setup-reset doctor clean lint test secrets quality smoke hooks fix messages worktree worktree-create worktree-remove tech-debt-check tech-debt-tidy tech-debt-create tech-debt-resolve

# Jméno za cílem (make worktree-create JMÉNO) make nehledá jako další cíl.
ifneq ($(filter worktree-create worktree-remove,$(MAKECMDGOALS)),)
.DEFAULT: ; @:
endif

help: ## Vypíše cíle
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/^([a-zA-Z_-]+):[^#]*## (.*)$$/  \1  \2/'

setup: ## Nainstaluje závislosti
	uv sync --frozen

setup-reset: clean setup ## Prostředí znovu od začátku: clean a setup

doctor: ## Ověří nástroje: uv, docker, docker compose, pre-commit hooky
	@uv --version
	@uv --version | awk '{split($$2, v, "."); if (v[1] == 0 && v[2] < 13) { print "uv je starý, projekt chce 0.13 nebo novější: uv self update"; exit 1 }}'
	@docker --version
	@docker compose version
	@test -f .git/hooks/pre-commit && echo "pre-commit hook: ok" || echo "pre-commit hook: chybí, spusť make hooks"

# Záměrně výčet cest, ne `git clean -X`: ten by smazal i .env, databáze a zálohy.
clean: ## Smaže build prostředí: .venv, cache nástrojů a výstupy buildu; data se nemažou
	rm -rf .venv .pytest_cache .ruff_cache .mypy_cache .coverage htmlcov dist build
	find . -type d \( -name .git -o -name .worktrees \) -prune -o -type d -name __pycache__ -prune -exec rm -rf {} +

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

quality: lint test secrets tech-debt-check ## Lint, testy, gitleaks a kontrola TECH_DEBT.md (to samé běží v CI)

smoke: ## Ověří nasazení: Docker Compose, Caddy, zdraví aplikace
	sh deploy/smoke.sh

messages: ## Vytáhne texty k překladu a zkompiluje katalogy (locale/)
	uv run python -m tools.messages

hooks: ## Nainstaluje git hooky
	pre-commit install

worktree: ## Vypíše worktree
	@git worktree list

worktree-create: ## Založí worktree: make worktree-create JMÉNO (větev JMÉNO v .worktrees/JMÉNO)
	@case "$$WT_NAME" in ''|-*|/*|*..*|*[!A-Za-z0-9._/-]*) echo "Použití: make worktree-create JMÉNO (písmena, číslice, . _ / -)" >&2; exit 1;; esac
	git worktree add "$(WT_DIR)/$$WT_NAME" -b "$$WT_NAME"

worktree-remove: ## Odstraní worktree a smaže větev, jen když je mergnutá
	@case "$$WT_NAME" in ''|-*|/*|*..*|*[!A-Za-z0-9._/-]*) echo "Použití: make worktree-remove JMÉNO (písmena, číslice, . _ / -)" >&2; exit 1;; esac
	git worktree remove "$(WT_DIR)/$$WT_NAME"
	git branch -d "$$WT_NAME"

tech-debt-check: ## Ověří TECH_DEBT.md a archiv
	@$(TECH_DEBT) check

tech-debt-tidy: ## Přesune vyřešené položky do archivu
	@$(TECH_DEBT) tidy

tech-debt-create: ## Založí položku: make tech-debt-create title="Název"
	@test -n "$$title" || { echo 'Použití: make tech-debt-create title="Název"' >&2; exit 1; }
	@$(TECH_DEBT) create "$$title"

tech-debt-resolve: ## Uzavře položku: make tech-debt-resolve id=TD-NNN
	@test -n "$$id" || { echo "Použití: make tech-debt-resolve id=TD-NNN" >&2; exit 1; }
	@$(TECH_DEBT) resolve "$$id"
