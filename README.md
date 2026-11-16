# Kvízotron

„Zapni mozek. Spusť Kvízotron.“

Self-hosted platforma pro vícejazyčné kvízy (cs/en/uk) a soutěže. Veřejnost hraje bez registrace přes
URL nebo QR kód. Lokální admini tvoří kvízy, spouštějí soutěžní běhy se žebříčkem a odměnami a
provádějí auditovatelné losování.

**Stav:** hotové jsou všechny etapy A až D. Admin napíše kvíz v cs/en/uk (typy otázek Výběr, Přiřazení, Číslo, Text a Fotka), publikuje ho a otevře běh s QR kódem; účastník hraje bez registrace a skóre spočítá server. Běžící kvíz jde bezpečně změnit. K tomu patří žebříčky, odměny a losování, export výsledků, mazání dat po uplynutí doby uchování, správa modulů, limity požadavků, denní záloha s ruční obnovou a zátěžový test 50 účastníků. Aplikace je určena i na veřejné nasazení, ale jen v topologii Compose s Caddy a jedním procesem aplikace ([nasazení](docs/deployment.md)). Před verzí 1.0 zbývají kontroly vydání a třídění technického dluhu.

## Dokumentace

- [Architektura](docs/_architecture/README.md) — začni tady
- [Roadmapa](docs/_architecture/roadmap.md)
- [Rozhodnutí (ADR)](docs/_architecture/adr/README.md)
- [Plugin API](docs/plugin-api.md), [nasazení](docs/deployment.md), [konfigurace](docs/configuration.md), [soukromí](docs/privacy.md)

## Instalace a použití

Vyzkoušení v Dockeru na vlastním stroji:

```sh
export KVZ_DOMAIN=localhost KVZ_SECRET_KEY=$(openssl rand -hex 32) KVZ_HTTP_PORT=18080 KVZ_HTTPS_PORT=18443
docker compose -f deploy/compose.yaml up --build -d --wait
docker compose -f deploy/compose.yaml run --rm -it app python manage.py init_admin admin
```

Potom otevři <https://localhost:18443/admin/login>. Prohlížeč upozorní na lokální certifikát Caddy. `KVZ_SECRET_KEY` si nech pro další spuštění, jinak přestanou platit přihlášení a rozehrané pokusy.

Ostré nasazení popisuje [docs/deployment.md](docs/deployment.md).

## Vývoj

- `make help` — seznam cílů
- `make env-update` — nainstaluje verze nástrojů, které projekt deklaruje (uv, Python a balíčky, pre-commit s hooky, Docker image)
- `make setup` — nainstaluje závislosti (vyžaduje uv z `pyproject.toml`, viz `make env-update`)
- `make hooks` — nainstaluje git hooky (gitleaks)
- `make lint`, `make test`, `make secrets` — jednotlivé kontroly
- `make quality` — všechny kontroly; totéž běží v CI
- `make smoke` — ověří celé nasazení v Dockeru
- `make load` — zátěž v Dockeru: 50 účastníků s fotkami, záloha, obnova a zkouška adres
- `make messages` — vytáhne texty k překladu a zkompiluje katalogy

## Licence

[GNU GPL](LICENSE). Bezpečnostní problémy hlaste podle [SECURITY.md](SECURITY.md).
