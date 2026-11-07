# Modul: app/domain

Kvíz, revize, kolo a pokus: modely, jejich pravidla a služby, které volají view. Pojmy definuje `docs/_architecture/modules/domain.md`.

## Odpovědnosti

- `models.py`: `Quiz`, `QuizRevision`, `QuizRun`, `RunRevision`, `Attempt`, `AppSetting`, `QuestionBank`, `BankQuestion`.
- `authoring.py`: koncept, publikace, návrat, zahození, kola, duplikace, archivace.
- `attempts.py`: start, submit, přepnutí pokusu, skóre. `tokens.py`: podepsaný token pokusu.
- `banks.py`: banky otázek. `selection.py`: které otázky pokus dostane, losování bez opakování. `questions.py`: co má každá uložená otázka. `reveal.py`: co se účastníkovi řekne o otázce.
- `settings.py`: nastavení aplikace (otázka → kvíz → globální hodnota → výchozí, ADR-0042). `external_images.py`: ze kterých adres kvíz opravdu načítá obrázky.
- `preview.py`: náhled bez ukládání (neuložený `Attempt` z podepsaného tokenu). `run_links.py`: testovací odkazy (ADR-0044).
- `question_import.py`: co znamenají řádky importu, `question_export.py`: co obsahuje stažený soubor (ADR-0045).
- `grading.py`: co rozhoduje člověk o uložené odpovědi, přepočet skóre. `visibility.py`: kdo smí vidět odpověď a fotku, stránky se ptají jen tady. `walkthrough.py`: veřejný průchod během (ADR-0046, ADR-0047). `requirements.py`: požadavky modulů na nastavení (ADR-0034).
- `revision_diff.py`: porovnání snapshotů pro přehled změn.
- `usage.py`: které moduly potřebují otevřená kola.

## Zakázáno

- Importovat z `app/api`, `app/plugins`, `app/providers`: typ otázky a bodování jdou přes `registry.get`.
- `save()` na revizi, která není koncept: `QuizRevision.save` to odmítne. Stav mění jen `.filter().update()`, obsah nikdy.
- Znovu vyhodnotit nebo přesunout existující pokus na jinou revizi: přepnutí vytváří nový pokus.
- Upravovat archivovaný kvíz: služby začínají `ensure_editable`.
- Řetězce pro uživatele bez `gettext`. Doména má vlastní katalog v `locale/`.

## Pozor

- `title`, `supported_locales` a `default_locale` žijí do publikace na řádku `Quiz`, ne v konceptu. Koncept drží jen otázky a losovací řádky (bez zásoby: ta vzniká při publikaci).
- Transakce jsou `IMMEDIATE`, takže kontrola a zápis v jednom `atomic()` nezávodí. `with_retry` řeší jen zámek SQLite.
- Do auditu ani logu nepatří odpovědi ani token testovacího odkazu.
- `QuizRun.objects` a `quiz.runs` testovací běhy nevidí a `QuizRevision.objects` nevidí testovací kopie, kdo je chce, volá `all_kinds`. Dotaz na `Attempt` napříč běhy musí druh běhu filtrovat sám.

## Veřejné API

Funkce a výjimky z `authoring`, `attempts`, `settings`, `revision_diff.compare`. Název začínající `_` je vnitřní.
