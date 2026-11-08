---
name: kvizotron-browser-walkthrough
description: Use when a Kvízotron change affects what a person sees or clicks (templates, CSS, JavaScript, HTMX, translations) and needs checking in a real browser, or when using or rebuilding the kvizotron-browser Docker stack.
---

# Průchod v prohlížeči

Testy vidí HTML, ne prohlížeč: CSS, JavaScript a dědění `hx-*` ověří až tenhle průchod.

## Data stacku zůstávají

Stack `kvizotron-browser` (`https://localhost:18443`) používá i uživatel.

- Svazky se nemažou a stack se nezakládá znovu. Na každé ověření založ **nový kvíz** s předponou milníku, třeba `c2-`.
- Jeho globální nastavení neměň. Potřebuješ jinou hodnotu? Použij přepsání na svém novém kvízu.
- Hotové kvízy po ověření nech být, úklid nenabízej.
- Mazání svazků zastaví i hook `.claude/hooks/guard_docker_volumes.py`.

## Sestavení z aktuálního kódu

Tajný klíč se přebírá z běžícího kontejneru, aby přihlášení a tokeny platily dál. Nikdy ho nevypisuj.

```bash
KVZ_SECRET_KEY="$(docker inspect kvizotron-browser-app-1 --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^KVZ_SECRET_KEY=//p')" \
KVZ_DOMAIN=localhost KVZ_HTTP_PORT=18080 KVZ_HTTPS_PORT=18443 \
docker compose -p kvizotron-browser -f deploy/compose.yaml up -d --build
```

Když stack neběží, klíč není odkud vzít: zeptej se uživatele.

## Skript

Načti `mcp__plugin_playwright_playwright__browser_run_code_unsafe` a vyjdi z `walk.template.js` vedle tohoto souboru. Doplň `BASE`, `ADMIN_STATE` a `SHOTS` a kroky piš do označeného místa. Upravenou kopii ulož do `.playwright-mcp/`, který je mimo git, a spusť ji přes parametr `filename`; odjinud ji nástroj odmítne.

Přihlášení je v souboru s uloženým stavem v `.playwright-mcp/`, který je mimo git. Když vypršelo, stránka přesměruje na `login`: heslo si vyžádej od uživatele, do skriptu ani výstupu ho nepiš.

## Co projít

| Pohled | Nastavení |
|---|---|
| Hlavní | 1280 px, světlý, `cs` |
| Telefon | 390 px, tmavý, `uk` |
| Klávesnice | hlavní cesta jen přes Tab a Enter |

U každého pohledu:

- Otevři screenshot a podívej se na něj. Text stránky nestačí, chybějící CSS v něm nepoznáš.
- Pole `errs` ze šablony musí být prázdné.
- Vyzkoušej i cestu účastníka v čistém kontextu bez přihlášení.
- U změny závislé na čase počítej s čekáním na skutečnou chvíli, nebo si ji nastav co nejblíž.

## Časté chyby skriptů

| Chyba | Správně |
|---|---|
| `button[type=submit]` klikne na formulář v záhlaví | `form:has([name=starts_at]) button[type=submit]` |
| Kliknutí bez čekání, čte se stará stránka | `await page.waitForLoadState()` po každém odeslání |
| Navigace na stránku kvízu, který nikdo nespustil | Nejdřív spusť běh a ověř, že je otevřený |

Než obviníš aplikaci, ověř, že skript klikl na to, co jsi chtěl: vypiš si URL a začátek `main`.

## Zpráva

Napiš, co jsi prošel a co ne. Co jsi v prohlížeči neviděl, označ jako ověřené jen testy. Nález v aplikaci opravuj testem, který nejdřív selže.
