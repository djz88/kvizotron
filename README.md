# Kvízotron

„Zapni mozek. Spusť Kvízotron.“

Self-hosted platforma pro vícejazyčné kvízy (cs/en/uk) a soutěže. Veřejnost hraje bez registrace přes
URL nebo QR kód. Lokální admini tvoří kvízy, spouštějí soutěžní kola se žebříčkem a odměnami a
provádějí auditovatelné losování.

**Stav:** hotová etapa A. Admin napíše kvíz s jednou správnou odpovědí v cs/en/uk, publikuje ho a otevře kolo s QR kódem; účastník odehraje kvíz a skóre spočítá server. Žebříčky, odměny a další typy otázek přijdou v dalších etapách. Na veřejné nasazení zatím není určeno, chybí limity požadavků (D5).

## Dokumentace

- [Architektura](docs/_architecture/README.md) — začni tady
- [Roadmapa](docs/_architecture/roadmap.md)
- [Rozhodnutí (ADR)](docs/_architecture/adr/README.md)
- [Plugin API](docs/plugin-api.md), [nasazení](docs/deployment.md), [soukromí](docs/privacy.md)

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
- `make setup` — nainstaluje závislosti (vyžaduje uv 0.13 nebo novější)
- `make hooks` — nainstaluje git hooky (gitleaks)
- `make lint`, `make test`, `make secrets` — jednotlivé kontroly
- `make quality` — všechny kontroly; totéž běží v CI
- `make smoke` — ověří celé nasazení v Dockeru
- `make messages` — vytáhne texty k překladu a zkompiluje katalogy

## Licence

[GNU GPL](LICENSE). Bezpečnostní problémy hlaste podle [SECURITY.md](SECURITY.md).
