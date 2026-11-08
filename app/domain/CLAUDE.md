# Modul: app/domain

Kvíz, revize, kolo a pokus: modely, jejich pravidla a služby, které volají view. Pojmy definuje `docs/_architecture/modules/domain.md`.

## Odpovědnosti

- `models.py`: `Quiz`, `QuizRevision`, `QuizRun`, `RunRevision`, `Attempt`, `Participant`, `AppSetting`, `QuestionBank`, `BankQuestion`, `RewardRule`, `RewardEntitlement`, `Draw`, `DrawEntry`.
- `authoring.py`: koncept, publikace, návrat, zahození, kola, duplikace, archivace.
- `attempts.py`: start, submit, přepnutí pokusu, skóre. `tokens.py`: podepsaný token pokusu.
- `run_schedule.py`: plán běhu, co čas učinil splatným (`settle`), uzávěrka, archivace, neodeslané pokusy (ADR-0048). `clock.py`: čtení a zobrazení času v nastaveném pásmu.
- `banks.py`: banky otázek. `selection.py`: které otázky pokus dostane, losování bez opakování. `questions.py`: co má každá uložená otázka. `reveal.py`: co se účastníkovi řekne o otázce.
- `settings.py`: nastavení aplikace (otázka → kvíz → globální hodnota → výchozí, ADR-0042); každé má `group` a `level` jen pro stránky administrace (ADR-0052). Výchozí průchod je po otázce, migrace 0015 nechává stávající instalaci na „vše najednou“. `external_images.py`: ze kterých adres kvíz opravdu načítá obrázky.
- `preview.py`: náhled bez ukládání (neuložený `Attempt` z podepsaného tokenu). `run_links.py`: testovací odkazy (ADR-0044).
- `question_import.py`: co znamenají řádky importu, `question_export.py`: co obsahuje stažený soubor (ADR-0045).
- `grading.py`: co rozhoduje člověk o uložené odpovědi, přepočet skóre. `visibility.py`: kdo smí vidět odpověď a fotku, stránky se ptají jen tady. `walkthrough.py`: veřejný průchod během (ADR-0046, ADR-0047). `requirements.py`: požadavky modulů na nastavení (ADR-0034).
- `data_policy.py`: profil dat a doba uchování u běhu (`retention_json`), co `none` vylučuje (ADR-0050). Rozhoduje se tu, co pokus uloží; `attempts.effective_profile(run)` platí i pro testovací běh.
- `participants.py`: pravidla účastníků na běhu, hash cookie, kdo smí začít nebo pokračovat, jméno a e-mail, tabulka pokusů. `access_codes.py`: přístupový kód jen jako hash a odemykací token (ADR-0049).
- `results.py`: nastavení žebříčku u běhu (`results_json`, `seed`, `merged`), konflikty, žebříček (`board`, `place_of`, `is_public`), sloučení revizí (ADR-0051). Pořadí a shody počítá plugin `result_view`. `run_stats.py`: statistiky běhu a porovnání běhů.
- `rewards.py`: nastavení odměn u běhu (`rewards_json`), pravidla odměn běhu a šablona kvízu (pravidlo bez běhu), kopie pravidel při plánu nebo otevření podle `reward_source`, konflikty (`profile`, `reveal`, `contact`). Strukturu pravidla jde měnit jen u naplánovaného běhu a v šabloně, texty kdykoli. Nároky (`refresh`) z oficiálního pokusu (`results.official_attempt`) v transakci odeslání a hodnocení; přepočet ruší jen automaticky udělené a nepředané a nikdy znovu neudělí, co zrušil správce; ruční udělení, předání a zrušení s důvodem jsou v auditu bez jmen (ADR-0053).
- `draws.py`: losování ceny u pravidla `draw` (FR-37, FR-38, ADR-0013): náhled způsobilých, `refusal` (proč by losování teď neprošlo, jen čte), losování, posun náhradníka, náhradní výherce, nové losování a zveřejnění výherců. Jen u uzavřeného nebo archivovaného běhu bez čekajícího hodnocení a mimo profil `none`; každý krok je nový řádek `Draw`, starý se nikdy nemění, audit nese jen pseudonymy (`pseudonym`: solený HMAC-SHA256 id účastníka). Posun bere prvního náhradníka, který je způsobilý teď; přeskočení si drží místo. Nároky z losování zapisuje `rewards.py`.
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
- Do auditu ani logu nepatří odpovědi, token testovacího odkazu, přístupový kód, jméno ani e-mail.
- Kontrola opakování a stejného jména patří do téhož `atomic()` jako zápis pokusu. Pokus `ABANDONED` odmítá každý vstup s tokenem.
- `QuizRun.objects` a `quiz.runs` testovací běhy nevidí a `QuizRevision.objects` nevidí testovací kopie, kdo je chce, volá `all_kinds`. Dotaz na `Attempt` napříč běhy musí druh běhu filtrovat sám.
- Pod profilem `none` se pokus maže při odeslání spolu s řetězem `replaced_by` a počet roste v téže transakci; testovací běh ho nezvyšuje. Doba trvání se ukládá jen pod `detailed`.
- Starší pokusy mají v `settings_json` ještě `store_answers`; čte je `data_policy.profile_of_attempt`.
- Cookie účastníka rozhoduje `participants.needs_participant(run)`: pravidla běhu, viditelný žebříček, nebo pravidla odměn. Veřejný žebříček je 5 s v mezipaměti (`kvz-board:<běh>:<jazyk>`); testy ji čistí v `tests/conftest.py`.
- Oficiální pokus pro odměny a losování vybírá `results.official_attempt` ze všech pokusů účastníka v běhu bez ohledu na režim revizí žebříčku; u `separate` a `latest` může žebříček počítat jiný pokus.
- Zrušení nároku správcem pozná `refresh` podle `changed_by`; automatické zrušení proto musí `changed_by` nechat prázdné.
- Žebříček nesmí ukázat e-mail ani id; řádek „vy“ se pozná jen podle cookie (`BoardRow.key`), nikdy podle jména.

## Veřejné API

Funkce a výjimky z `authoring`, `attempts`, `settings`, `revision_diff.compare`. Název začínající `_` je vnitřní.
