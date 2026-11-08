# Modul: tests

Struktura kopíruje `app/`. Pravidla pro testy jsou v kořenovém `CLAUDE.md`; tady je, jak jsou postavené.

## Kde co je

- `contracts/`: sady, které musí projít každý modul. `question_type.py` je základ, `test_<typ>.py` ho dědí.
- `domain/`, `api/`, `kernel/`, `providers/`: testy jednotlivých vrstev.
- `integration/`: celé toky přes HTTP a testy v samostatném procesu.
- `test_docs.py`: ID v dokumentaci, odkazy, cesty a jména skillů a AC, které žádný test nejmenuje; ten seznam se smí jen zmenšovat, nové AC potřebuje test se svým ID. `test_agent_hooks.py`: hook proti mazání svazků. `test_wiring.py`: moduly, šablony, adresy, skripty, styly a nastavení jsou napojené.
- `support/`: `FormClient`, `run_manage`, `make_module`, `waiting` (`busy.py`: opakuje volání při zámku sdílené testovací databáze, kde SQLite nečeká jako v provozu). `fixtures/`: ukázkové moduly a instalace pro AC-01 a AC-02.
- `domain/helpers.py`: staví kvízy přes tytéž služby jako administrace.

## Pozor

- Odesílej přes `FormClient` nebo fixture `client`. Čistý `django.test.Client` posílá multipart a aplikace ho odmítne s 415.
- Publikace přes HTTP potřebuje `snapshot_hash` ze stránky publikace. Přes službu při běžícím kole potřebuje `decision`.
- Nový test v `contracts/question_type.py` mění počet v `contracts/test_demo_question.py`.
- Nový typ otázky v `fixtures/demo_site` mění počet v `contracts/test_demo_question.py`.
- Multipart s obrázkem posílej čistým `Client` po `force_login` a nastav `settings.KVZ_MEDIA_PATH` na `tmp_path`.
- Testy vidí HTML, ne prohlížeč. Dědění HTMX atributů odhalil až průchod v prohlížeči: změnu `hx-*` si ověř i tam.

## Není tady

Skutečné přihlašovací údaje a síť. Hesla v testech jsou testovací hodnoty; přijaté nálezy skenerů jsou v `docs/_architecture/security.md`.
