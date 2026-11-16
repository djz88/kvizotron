# Vygenerováno heimdallem. Cíl quality je jediný zdroj pravdy pro CI: CI má volat
# `make quality`, ne vlastní příkazy. `make lint fix` spustí lint s opravami (příkaz
# lintu k tomu používá $(LINT_FIX), pokud nástroj opravy umí).
.DEFAULT_GOAL := help
LINT_FIX := $(if $(filter fix,$(MAKECMDGOALS)),--fix)
WT_DIR := .worktrees
WT_NAME = $(or $(name),$(word 2,$(MAKECMDGOALS)))
export WT_NAME
# pre-commit běží na Pythonu 3.14: potřebuje PyYAML, který pro 3.15 nemá wheel.
PRE_COMMIT := uvx --python 3.14 pre-commit@4.7.0
# compose bez nich soubor nepřečte; žádný kontejner se s nimi nespouští.
COMPOSE_IMAGES := KVZ_SECRET_KEY=unused KVZ_DOMAIN=localhost docker compose -f deploy/compose.yaml
TECH_DEBT := python3 tools/tech_debt.py --doc docs/_architecture/TECH_DEBT.md
# Verze, které projekt chce. uv: `[tool.uv] required-version` v pyproject.toml, doplněná na x.y.z;
# Dockerfile instaluje tutéž (hlídá tests/test_makefile.py). Python a balíčky: pyproject.toml a uv.lock.
# Hooky: .pre-commit-config.yaml. Image: digesty v Dockerfile a deploy/compose.yaml.
UV_REQUIRED := $(shell sed -n 's/^required-version *= *">=\([0-9.]*\)".*/\1/p' pyproject.toml 2>/dev/null | awk -F. '{print $$1"."$$2"."($$3==""?0:$$3)}')
.PHONY: wiring plan-check help env-update setup setup-reset doctor clean lint test secrets quality smoke load hooks fix messages worktree worktree-create worktree-remove tech-debt-check tech-debt-tidy tech-debt-create tech-debt-resolve

# Jméno za cílem (make worktree-create JMÉNO) make nehledá jako další cíl.
ifneq ($(filter worktree-create worktree-remove,$(MAKECMDGOALS)),)
.DEFAULT: ; @:
endif

help: ## Vypíše cíle
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/^([a-zA-Z_-]+):[^#]*## (.*)$$/  \1  \2/'

env-update: ## Nainstaluje verze, které projekt deklaruje: uv, Python a balíčky, pre-commit s hooky, Docker image
	uv self update $(UV_REQUIRED)
	uv sync --frozen
	$(PRE_COMMIT) install --install-hooks
	$(COMPOSE_IMAGES) pull --ignore-buildable
	$(COMPOSE_IMAGES) build --pull

setup: ## Nainstaluje závislosti
	uv sync --frozen

setup-reset: clean setup ## Prostředí znovu od začátku: clean a setup

doctor: ## Ověří nástroje: uv, docker, docker compose, pre-commit hooky
	@uv --version
	@uv --version | awk -v want="$(UV_REQUIRED)" '{split($$2, v, "."); split(want, w, "."); for (i = 1; i <= 3; i++) { if (v[i] + 0 > w[i] + 0) exit 0; if (v[i] + 0 < w[i] + 0) { print "uv je starý, projekt chce " want " nebo novější: make env-update"; exit 1 } }}'
	@docker --version
	@docker compose version
	@test -f .git/hooks/pre-commit && echo "pre-commit hook: ok" || echo "pre-commit hook: chybí, spusť make env-update"

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

secrets: ## Hledá tajné údaje (gitleaks) ve staged změnách a v historii gitu
	$(PRE_COMMIT) run --all-files
	$(PRE_COMMIT) run --all-files --hook-stage manual gitleaks-history

quality: lint test secrets tech-debt-check ## Lint, testy, gitleaks a kontrola TECH_DEBT.md (to samé běží v CI)

wiring: ## Jen kontroly napojení: moduly, šablony, adresy, skripty, styly, nastavení
	uv run pytest tests/test_wiring.py -q

plan-check: ## Změnily se soubory z plánu? make plan-check plan=cesta.md base=main
	@test -n "$(plan)" || { echo "Použití: make plan-check plan=docs/superpowers/plans/x.md [base=main]"; exit 2; }
	python3 -m tools.plan_check --plan "$(plan)" --base "$(or $(base),main)"

smoke: ## Ověří nasazení: Docker Compose, Caddy, zdraví aplikace
	sh deploy/smoke.sh

load: ## Zátěž: 50 účastníků odešle fotky naráz při záloze, obnova a zkouška adres (Docker, minuty)
	sh deploy/load.sh

messages: ## Vytáhne texty k překladu a zkompiluje katalogy (locale/)
	uv run python -m tools.messages

hooks: ## Nainstaluje git hooky
	$(PRE_COMMIT) install

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
