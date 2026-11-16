# Toky Kvízotronu

Každý tok: kdy se ho změna týká, články v pořadí, co může odmítnout a čím se to spouští.

## Hraní

- **Týká se:** `app/api/play.py`, `app/domain/attempts.py`, `app/api/rendering.py`, `app/plugins/questions/`, `app/plugins/scoring/`, `app/plugins/quiz_flow/`
- **Články:** `/q/<slug>` → `/r/<id>/start` → `attempts.start` a podepsaný token (průchod a velikost stránky zamrzlé v `settings_json`) → stránka bez klíče odpovědí a `flow.js` po otázce nebo po stránkách → `/a/<id>/check` → `/a/<id>/submit` → `attempts.submit` → `grade` typu a váha strategie → výsledek a odhalení.
- **Odmítnutí:** uzavřený běh, špatný token, opakované odeslání, pozměněné skóre.
- **Spuštění:** `uv run pytest tests/integration/test_vertical_slice.py tests/integration/test_banks_and_flow.py tests/api/test_play.py tests/api/test_play_flow.py tests/api/test_play_check.py tests/api/test_play_reveal.py tests/domain/test_attempts.py -q`

## Obsah a publikace

- **Týká se:** `app/domain/authoring.py`, `app/domain/banks.py`, `app/domain/selection.py`, `app/domain/revision_diff.py`, `app/api/admin_quizzes.py`, `app/api/admin_revisions.py`, `app/api/admin_banks.py`
- **Články:** editor → koncept → přehled změn → publikace a neměnná revize → otevření běhu → losování otázek při startu.
- **Odmítnutí:** chybějící překlad, nesplněné požadavky modulů, kvíz změněný po zobrazení přehledu.
- **Spuštění:** `uv run pytest tests/api/test_question_editor.py tests/api/test_admin_quizzes.py tests/api/test_admin_revisions.py tests/api/test_admin_banks.py tests/domain/test_authoring.py tests/domain/test_publish_and_open.py tests/domain/test_revision_diff.py tests/domain/test_selection.py -q`

## Nová revize za běhu

- **Týká se:** `app/domain/attempts.py`, `app/domain/authoring.py`, `app/api/play.py`, `app/api/jinja2/public/_questions.html`
- **Články:** publikace při běžícím běhu → volba politiky → `/a/<id>/revision-status` → upozornění na stránce → `/a/<id>/switch` → převzaté odpovědi a původní začátek.
- **Odmítnutí:** staré odeslání po přepnutí, dvojí kliknutí, přepnutí po čase.
- **Spuštění:** `uv run pytest tests/integration/test_revision_switch.py tests/api/test_switch.py tests/domain/test_switch.py tests/domain/test_run_revisions.py -q`

## Plán a čas

- **Týká se:** `app/domain/run_schedule.py`, `app/api/run_clock.py`, `app/domain/clock.py`, `app/api/admin_runs.py`, `app/api/assets/countdown.js`, `app/api/assets/planned.js`, `app/api/assets/clock.js`
- **Články:** `/admin/quizzes/<id>/plan` → `run_schedule.plan` → první požadavek po termínu a `settle` → otevřený běh → start s limitem → odpočet a `/a/<id>/time` → automatické odeslání (`countdown.js` ho opakuje se stejným klíčem po chybě spojení, 5xx a 429, `start` nikdy) → čas příjmu při `submit` → uzavření a počet neodeslaných → archiv.
- **Odmítnutí:** start před termínem, odeslání po limitu, pozdní fotka, nesplněné požadavky při otevření.
- **Spuštění:** `uv run pytest tests/api/test_countdown_script.py tests/api/test_run_plan.py tests/api/test_planned_quiz.py tests/api/test_run_deadline.py tests/api/test_countdown.py tests/api/test_run_archive.py tests/domain/test_run_schedule.py tests/domain/test_attempt_time.py tests/domain/test_clock.py -q`
- **Mimo testy:** `tools/load_deadline.py` při změně cesty odeslání, skutečné odeslání v prohlížeči přes `kvizotron-browser-walkthrough`.

## Účastníci a přístupový kód

- **Týká se:** `app/plugins/participants/`, `app/domain/participants.py`, `app/domain/access_codes.py`, `app/api/rate_limit.py`, `app/api/play.py`, `app/api/public.py`, `app/api/admin_runs.py`, `app/api/jinja2/public/_identity_fields.html`
- **Články:** pravidla kvízu → kopie na běh při plánu nebo otevření → kód na `/r/<id>/code` a odemykací cookie → `/r/<id>/start`: brána kódu, jméno před startem, cookie účastníka a `participants.begin` (nový, pokračuje, nahradí, odmítne) → `/a/<id>/submit`: kontrola opakování a jména v jedné transakci → výsledek s doplněním přes `/v/<token>/identity` → tabulka pokusů u běhu.
- **Odmítnutí:** chybějící nebo změněný kód, jedenáctý špatný kód za minutu, už odehráno, čas vypršel, opuštěný pokus, obsazené jméno, chybějící povinné jméno nebo e-mail.
- **Spuštění:** `uv run pytest tests/contracts/test_participants.py tests/domain/test_participant_rules.py tests/domain/test_repetition.py tests/domain/test_identity.py tests/domain/test_access_codes.py tests/api/test_participant_cookie.py tests/api/test_identity_flow.py tests/api/test_access_code_flow.py tests/api/test_run_attempts_table.py tests/integration/test_no_personal_data_in_logs.py -q`
- **Mimo testy:** `make smoke` pro IP za Caddy, průchod v prohlížeči pro chybu jména v krokovém režimu.

## Fotky a hodnocení

- **Týká se:** `app/plugins/questions/image_answer/`, `app/providers/media_local/`, `app/domain/grading.py`, `app/domain/visibility.py`, `app/domain/walkthrough.py`, `app/api/admin_grading.py`, `app/api/public.py`
- **Články:** vícedílné odeslání → kontrola a přestavění fotky → soukromé uložení → pokus čeká na hodnocení → `/admin/quizzes/<id>/grading` → známka → soukromý odkaz `/v/<token>` → veřejný průchod.
- **Odmítnutí:** převlečený soubor, limit běhu, pozdní fotka, cizí token, fotka bez schválení.
- **Spuštění:** `uv run pytest tests/api/test_image_answer.py tests/api/test_image_check.py tests/api/test_grading.py tests/api/test_stored_answers.py tests/api/test_result_link.py tests/api/test_walkthrough.py tests/providers/test_media_participant.py tests/domain/test_grading.py tests/domain/test_visibility.py -q`

## Profil dat a pokračování

- **Týká se:** `app/domain/data_policy.py`, `app/domain/attempts.py`, `app/domain/run_schedule.py`, `app/api/play.py`, `app/api/admin_runs.py`, `app/api/assets/resume.js`, `app/plugins/quiz_flow/manifest.py`
- **Články:** profil v nastavení → plán běhu a kopie do běhu → start → odeslání (uloženo, nebo smazáno a započítáno) → stránka výsledku. A kopie v prohlížeči → `POST /r/<běh>/resume` → odeslání → kopie smazána.
- **Odmítnutí:** `none` s vylučujícím nastavením, druhé odeslání bez pokusu (410), token cizího nebo skončeného pokusu, vypnuté pokračování.
- **Spuštění:** `uv run pytest tests/domain/test_data_policy.py tests/domain/test_profile_storage.py tests/domain/test_stateless.py tests/domain/test_local_resume.py tests/domain/test_migration_0013.py tests/api/test_stateless_flow.py tests/api/test_local_resume.py tests/api/test_run_plan.py -q`

## Nastavení

- **Týká se:** `app/domain/settings.py`, `app/domain/requirements.py`, `app/api/admin_settings.py`, `app/api/admin_forms.py`, `manifest.py` modulů
- **Články:** katalog → pole na stránce rozsahu → uložení přepsání → `settings.resolve` → účinek na stránce hraní a v náhledu.
- **Odmítnutí:** volba mimo nabídku, konflikt s jiným nastavením, požadavek modulu blokující publikaci.
- **Spuštění:** `uv run pytest tests/contracts/test_settings_rule.py tests/domain/test_settings.py tests/domain/test_flow_settings.py tests/domain/test_requirements.py tests/api/test_admin_settings.py tests/api/test_requirements.py -q`

## Náhled a testovací odkaz

- **Týká se:** `app/domain/preview.py`, `app/domain/run_links.py`, `app/api/admin_preview.py`, `app/api/admin_links.py`, `app/api/public.py`
- **Články:** náhled bez ukládání, s volitelným limitem → odkaz `/t/<token>` na zvolenou revizi → testovací běh skrytý před výsledky.
- **Odmítnutí:** odeslání náhledu po limitu, zrušený nebo prošlý odkaz.
- **Spuštění:** `uv run pytest tests/api/test_preview.py tests/api/test_test_links.py tests/domain/test_run_links.py tests/domain/test_run_kinds.py -q`

## Import a export

- **Týká se:** `app/providers/csv_io/`, `app/domain/question_import.py`, `app/domain/question_export.py`, `app/api/admin_import.py`, `app/api/admin_export.py`, `from_csv` typů otázek
- **Články:** `/admin/import/new` → mapování → kontrola → potvrzení → přehled → koncept kvízu nebo banky → export → znovu import beze změny.
- **Odmítnutí:** chyba v řádku, poškozený nebo příliš velký ZIP, obrázek, který nejde stáhnout.
- **Spuštění:** `uv run pytest tests/integration/test_csv_round_trip.py tests/api/test_import.py tests/domain/test_question_import.py tests/domain/test_question_export.py tests/providers/test_csv_reader.py tests/providers/test_csv_writer.py tests/contracts/test_csv_io.py -q`

## Modul

- **Týká se:** `app/kernel/`, `app/contracts/`, `pyproject.toml`, `manifest.py` modulů
- **Články:** entry point → `load_modules` a pořadí závislostí → `INSTALLED_APPS` → `ready()` a registr → editor, hraní a vyhodnocení.
- **Odmítnutí:** chybějící závislost, nekompatibilní verze, klíč registrovaný dvakrát, vypnutý modul se starou revizí.
- **Spuštění:** `uv run pytest tests/integration/test_ac01_question_plugin.py tests/integration/test_demo_module.py tests/integration/test_installed_project.py tests/integration/test_startup_verification.py tests/integration/test_auth_switch.py -q`

## Výsledky a žebříček

- **Týká se:** `app/plugins/results/`, `app/domain/results.py`, `app/domain/run_stats.py`, `app/domain/participants.py` (`needs_participant`, `attempt_rows`), `app/api/scoreboard.py`, `app/api/play.py`, `app/api/public.py`, `app/api/admin_runs.py`, `app/api/jinja2/public/scoreboard.html`, `app/api/jinja2/public/_scoreboard_rows.html`
- **Články:** nastavení žebříčku kvízu → kopie do `results_json` se `seed` při plánu nebo otevření → viditelný žebříček nastaví cookie účastníka i při povoleném opakování → `/a/<id>/submit` a hodnocení → `results.board`: oficiální pokus a pořadí přes `result_view`, anonymizace, skrytí při čekajícím hodnocení, mezipaměť 5 s → `/q/<slug>/r/<id>/scoreboard` a fragment `/rows` každých 15 s → vlastní místo u výsledku → administrace: zobrazení, sloučení revizí, statistiky, porovnání běhů, řazení pokusů.
- **Odmítnutí:** viditelný žebříček s profilem `none` nebo s odpověďmi po každé otázce, doba trvání bez profilu `detailed`, sloučení s různým maximem nebo jednou revizí, testovací běh (404), archiv bez vypínače.
- **Spuštění:** `uv run pytest tests/contracts/test_results.py tests/domain/test_results_settings.py tests/domain/test_results_board.py tests/domain/test_run_stats.py tests/api/test_results_forms.py tests/api/test_scoreboard_page.py tests/api/test_admin_scoreboard.py tests/api/test_run_stats_page.py tests/api/test_attempts_table_sort.py tests/api/test_participant_cookie.py -q`
- **Mimo testy:** průchod v prohlížeči: obnovování při odeslání z jiného prohlížeče, projektor a celá obrazovka, telefon, tmavý režim, ukrajinština.

## Odeslání → nárok na odměnu

- **Týká se:** `app/plugins/rewards/`, `app/domain/rewards.py`, `app/domain/attempts.py` (`submit`), `app/domain/grading.py`, `app/domain/results.py` (`official_attempt`), `app/domain/authoring.py` a `app/domain/run_schedule.py` (`copy_rules`, `ensure_allowed`), `app/domain/participants.py` (`needs_participant`), `app/api/admin_rewards.py`, `app/api/admin_runs.py`, `app/api/play.py` (`rewards_shown`), `app/api/public.py`, `app/api/jinja2/public/_rewards.html`
- **Články:** pravidla v šabloně kvízu nebo předchozím běhu → `reward_source` → kopie pravidel a `rewards_json` při plánu nebo otevření a `ensure_allowed` → cookie účastníka → `/a/<id>/submit` → `rewards.refresh` v transakci odeslání: oficiální pokus, `reward.qualifies` podle `reward_thresholds` → udělení, nebo zrušení „no longer reached“ → konec hodnocení znovu `refresh` → výsledek a `/v/<token>` s pokyny k vyzvednutí → stránka odměn běhu: předání, zrušení s důvodem, ruční udělení.
- **Odmítnutí:** pravidla s profilem `none` nebo s odpověďmi po každé otázce, losování bez povinného e-mailu pod `require_email`, změna struktury na otevřeném běhu, testovací běh, čekající hodnocení, zrušení bez důvodu, ruční udělení pravidla jiného druhu nebo běhu.
- **Spuštění:** `uv run pytest tests/contracts/test_reward.py tests/plugins/test_reward_thresholds.py tests/domain/test_reward_rules.py tests/domain/test_entitlements.py tests/api/test_admin_rewards.py tests/api/test_public_rewards.py -q`
- **Mimo testy:** průchod v prohlížeči: pravidla v plánu, pokyny k vyzvednutí v cs/en/uk, telefon a tmavý režim.

## Uzavření → losování

- **Týká se:** `app/plugins/drawings/`, `app/domain/draws.py`, `app/domain/rewards.py` (`_grant_draw`, `_cancel_draw`, `public_winners`), `app/domain/grading.py` (`waiting`), `app/domain/data_policy.py`, `app/api/admin_rewards.py` (`run_draw`, `run_draw_action`), `app/api/jinja2/admin/prize_draw.html`, `app/api/scoreboard.py`
- **Články:** uzavření běhu → `/admin/runs/<id>/draw`: `draws.refusal` a náhled (počet, otisk) → POST `draw`: znovu sestavený snímek, `drawing.select` vítězů a náhradníků najednou, řádky `Draw` a `DrawEntry` s pseudonymy, audit a `draw.completed`, nároky vítězů → `move_up`, `substitute`, `redraw` s důvodem jako nové řádky → zveřejnění výherců → žebříček běhu.
- **Odmítnutí:** běh není uzavřený, profil `none`, čekající hodnocení, testovací běh nebo pravidlo jiného druhu, nikdo způsobilý, už losováno, chybějící důvod, žádný způsobilý náhradník, nikdo nezbyl pro náhradního výherce.
- **Spuštění:** `uv run pytest tests/contracts/test_drawing.py tests/plugins/test_draw_selection.py tests/domain/test_prize_draws.py tests/api/test_admin_draw.py tests/api/test_public_rewards.py -q`
- **Mimo testy:** průchod v prohlížeči: otisk na telefonu, posun náhradníka a zveřejnění výherců na žebříčku.

## Stránky nastavení

- **Týká se:** `app/api/admin_view.py`, `app/api/admin_settings.py`, `app/api/admin_quizzes.py` (`settings_page`), `app/api/admin_runs.py` (`_plan_page`), `app/api/jinja2/admin/_setting_groups.html`, `admin/_section_panel.html`, `settings.html`, `quiz_settings.html`, `run_plan.html`, `app/api/assets/sections.js`, `app/plugins/theme_default/assets/theme.css` (`.section-panel`), `_quiz_header.html`, `run.html`, `app/domain/settings.py` (`group`, `level`), manifesty modulů
- **Články:** `group` a `level` u nastavení → `group_fields` podle cookie `kvz_admin_view` a toho, co se liší od zděděné hodnoty → skupiny na stránce a panel sekcí s odkazy na kotvy a přepínačem Základní / Vše (i na stránce běhu, která podle zobrazení skrývá kód a data) (široká obrazovka: boční panel, úzká: plovoucí tlačítko „Sekce“ s `<details>`; `sections.js` jen označí aktuální sekci) → přepínač POST `/admin/view` s `next` zpět na stránku → POST bez skrytých polí → uložení, které prázdnou hodnotu bere jako beze změny.
- **Odmítnutí:** konflikt na skrytém poli ukáže pole i chybu; cizí `next` u přepínače vede na `/admin/`.
- **Spuštění:** `uv run pytest tests/domain/test_setting_groups.py tests/api/test_admin_view.py tests/api/test_run_plan.py tests/api/test_admin_layout.py tests/api/test_admin_settings.py -q`
- **Mimo testy:** průchod v prohlížeči: obě zobrazení, plán, „Více“ na telefonu, panel sekcí na široké obrazovce i plovoucí tlačítko na telefonu, klávesnice.

## Branding

- **Týká se:** `app/domain/branding.py`, `app/domain/models.py` (`BrandingConfiguration`), `app/plugins/theme_default/` (`colours.py`, `layout.html`, `theme.css`), `app/api/rendering.py` (`page`), `app/api/admin_branding.py`, `app/api/admin_forms.py`, `app/api/admin_settings.py`, `app/api/admin_quizzes.py` (`settings_page`), `app/api/admin_preview.py`, `app/api/play.py`, `app/api/public.py`, `app/api/scoreboard.py`, `app/api/jinja2/public/base.html`, `app/settings.py` (`SECURE_CSP`), `app/domain/creator.py`, `app/domain/models.py` (`Quiz.created_by`), `app/kernel/models.py` (`AdminUser.email`), `app/api/admin_users.py`, `app/plugins/theme_default/views.py` a `assets/badge-*.svg`
- **Články:** správce uloží texty a logo (`/admin/settings/branding`, `/admin/quizzes/<id>/branding`) nebo paletu a barvy (formulář nastavení, `require_colours`) → `branding.set_texts`, `set_logo`, `set_colours`, audit `branding.changed` bez hodnot → `branding.resolve(branding_quiz, locale)` po polích kvíz → globální → vestavěná hodnota, paleta a barvy z úrovně, která vybrala `custom` → `theme.derive_palette` upraví barvy pod WCAG AA → `rendering.page` dá šabloně `branding` a `csp_nonce` → rozložení tématu: název, logo, `data-palette`, blok `<style nonce>` jen u `custom` → `public/base.html`: jeden řádek patičky v pořadí text správce · `GPL-3.0-or-later` · odznaky Python, Django, HTMX (téma) · „Běží na Kvízotronu <verze>“ s odkazem na O aplikaci · rok v nastaveném pásmu · kontaktní e-mail (`mailto:`), chybějící díl vynechán. Kontaktní e-mail: `branding.set_contact_email` → `resolve` kvíz → globální → `creator.creator_email(quiz)` z `Quiz.created_by` (nový kvíz, duplikace, import; starší migrace `0018`) a `AdminUser.email` ze stránky Správci; bez kvízu nic. Stránky kvízu (hraní, výsledek, žebříček, projektor, náhled, testovací odkaz) předávají `branding_quiz`, ostatní berou globální.
- **Odmítnutí:** `custom` bez obou barev, barva mimo `#rrggbb`, text nad limit (název 80, heslo 160, patička 300), neplatný kontaktní e-mail nebo e-mail správce (nad 254 znaků), nepřijatý soubor loga, archivovaný kvíz (409).
- **Spuštění:** `uv run pytest tests/domain/test_branding.py tests/plugins/test_theme_colours.py tests/test_palettes.py tests/api/test_branding_pages.py tests/api/test_admin_branding.py tests/contracts/test_theme_default.py tests/domain/test_quiz_created_by.py tests/api/test_quiz_created_by.py tests/api/test_admin_users.py tests/kernel/test_admin_user.py -q`
- **Mimo testy:** průchod v prohlížeči: vlastní barvy ve světlém i tmavém režimu bez chyby CSP v konzoli, telefon, logo, náhled a testovací odkaz s barvami kvízu, řádek patičky na telefonu, ukrajinština.

## Export výsledků

- **Týká se:** `app/contracts/__init__.py` (`ExportTable`, `ExportJobView`, `ResultsExporterProvider`, `TableSinkProvider`), `app/providers/csv_io/` (`results.py`, `writer.write_table`, `models.ExportJobRecord`, `limits.py`), `app/domain/results_export.py`, `app/domain/results.py` (`board(audience="admin")`, `official_attempt`, `BoardRow.attempt_id`), `app/domain/run_stats.py` (`of_revision`), `app/domain/clock.py` (`iso`), `app/api/admin_results_export.py`, `app/api/export_runner.py`, `app/api/jinja2/admin/results_export.html`, `_export_jobs.html`, `run.html` (sekce Export), `runs.html` (zaškrtnutí v porovnání), `_quiz_header.html` (Exportovat výsledky)
- **Články:** běh, kvíz nebo porovnání běhů → `/admin/exports/new?quiz=&runs=` → `results_export.offered` podle profilu dat → POST se soubory, `bundle`, fotkami a potvrzením osobních údajů → `create` (řádek `export_job` `queued`, `choices_json`, `BOOT`) a audit `export.created` → `export_runner.kick()` → `claim_next()` (sloty 1 na správce, 2 v aplikaci) → vlákno: `results_export.tables` a `photo_files` → `write()` do `exports/<id>/` (CSV `;`, BOM, CRLF, ochrana proti vzorcům mimo čísla v `numeric`, nebo ZIP s fotkami) → `done` → fragment `/admin/exports/jobs` každé 2 s → stažení `/admin/exports/<id>/<soubor>` jen pro autora, audit `export.downloaded` → po 24 hodinách smazání při dalším použití stránky. Úloha z jiného procesu → `interrupted` → „Spustit znovu“.
- **Odmítnutí:** žádný soubor, soubor, který běhy nedávají, neplatný `bundle`, osobní údaje bez potvrzení (400); cizí, testovací nebo neznámý běh (404); stažení cizí, nehotové nebo prošlé úlohy (404); nové spuštění úlohy, která není `interrupted` ani `failed` (404); vlákno, které nejde spustit (`failed`).
- **Spuštění:** `uv run pytest tests/contracts/test_table_sink.py tests/contracts/test_csv_io.py tests/providers/test_csv_writer.py tests/providers/test_csv_results.py tests/domain/test_results_export.py tests/api/test_results_export.py -q`
- **Mimo testy:** skutečné vlákno (testy ho volají synchronně), průchod v prohlížeči: stránka exportu na počítači a telefonu, obnovování seznamu úloh, CSV otevřené v LibreOffice (rozdělené sloupce, diakritika), ZIP s fotkami.

## Mazání dat běhu

- **Týká se:** `app/domain/retention.py`, `app/domain/data_policy.py` (`deletion_at`, `is_due`, `days_left`, `deletion_soon`), `app/domain/run_stats.py` (`freeze`, čtení ze souhrnu), `app/domain/run_schedule.py` (`settle`, `set_period`), `app/domain/results.py` a `walkthrough.py` (stav `data_deleted`), `app/domain/migrations/0019_retention.py`, `app/domain/management/commands/` (`jobs.py`, `retention.py`), `app/domain/heartbeat.py` (záznam průchodu, řádek „Poslední průchod“ na `retention.html`), `app/domain/migrations/0020_participant_email_key.py`, `app/providers/retention/`, `app/providers/csv_io/results.py` (`delete_for_runs`), `app/providers/media_local/provider.py` (`private_assets_older_than`), `app/api/admin_retention.py`, `app/api/jinja2/admin/` (`retention.html`, `erasure.html`, `_erasure_rows.html`, `_deletion.html`, `run.html`, `runs.html`), `deploy/compose.yaml` (služba `jobs`)
- **Články:** služba `jobs` každou hodinu `run_pass` → `run_schedule.settle` → běh po době (`data_policy.is_due`, ne zadržený) nebo se souhrnem bez `data_deleted_at` → `purge_run`: souhrn s počty → pokusy po 200 (`replaced_by` napřed, fotky po commitu) → exporty → poslední transakce (hodnoty, nároky, účastníci, profil `none`, `ARCHIVED`, `data_deleted_at`, záznam `retention_job`, audit `run.data_deleted`, událost `retention.executed`) → pozdní exporty → `sweep`. „Smazat data teď“ (`delete_now`) jde stejnou cestou. Výmaz: `/admin/retention/erasure` POST → `search_email` (jeden dotaz podle `Participant.email_key`, nastaví ho `participants.claim_name`) nebo `search_name` → zaškrtnutí → potvrzení → `erase` po bězích (`run.participants_erased`, u e-mailu otisk; souhrn rozpracovaného mazání se sníží o smazané řádky; po commitu `results.clear_board_cache`) → `/admin/retention`. Souhrn drží `trigger`, `admin_id` a značku `late_exports_pending`, kterou `run_pass` pozdním odstraněním exportů po 24 hodin zkouší. Zadržený běh → `/admin/retention/held` → `release_held` → další průchod.
- **Odmítnutí:** smazání běhu, který neskončil (`not_ended`), změna doby smazaného běhu (`data_deleted`), zkrácení doby do minulosti bez potvrzení (`PeriodNeedsConfirmation`), žádné zaškrtnuté řádky výmazu, soubory exportu, které nejde odstranit (mazání se zastaví a další průchod naváže), veřejné stránky smazaného běhu (nedostupný stav).
- **Spuštění:** `uv run pytest tests/domain/test_retention_due.py tests/domain/test_retention_purge.py tests/domain/test_retention_pass.py tests/domain/test_retention_period.py tests/domain/test_retention_stats.py tests/domain/test_retention_erasure.py tests/domain/test_migration_0019.py tests/api/test_admin_retention.py tests/api/test_retention_public.py tests/contracts/test_retention.py tests/providers/test_export_retention.py -q`
- **Mimo testy:** skutečná služba `jobs` (`make smoke`, healthcheck služby `jobs` po minutě), průchod v prohlížeči: Historie mazání s řádkem „Poslední průchod“ před průchodem a po něm, zadržené běhy, žádost o výmaz, datum smazání na běhu a v seznamu běhů v obou barevných režimech a na telefonu.

## Vypnutí modulu

- **Týká se:** `app/kernel/lifecycle.py` (`blockers`, `set_enabled`), `app/domain/usage.py`, `app/domain/plugin_overview.py`, `app/api/admin_plugins.py`.
- **Články:** `/admin/plugins` → `/admin/plugins/{id}` → POST `/admin/plugins/{id}/state` → `lifecycle.set_enabled` → `registry.is_enabled` → editor, publikace, náhled a odměny přestanou plugin nabízet; uložený obsah čte `include_disabled=True`.
- **Odmítnutí:** poskytovatel, `always_on`, poslední téma, naplánovaný nebo otevřený běh, živé pravidlo odměny, závislost jiného modulu. Stránka odpoví 409 s důvody v jazyce správce.
- **Spuštění:** `uv run pytest tests/kernel/test_lifecycle.py tests/domain/test_usage.py tests/domain/test_plugin_overview.py tests/api/test_admin_plugins.py tests/api/test_disabled_plugin.py -q`
- **Mimo testy:** průchod v prohlížeči: seznam modulů, vypnutí typu otázky, detail s „Jinde jinak“, telefon.

## Omezení požadavků

- **Týká se:** `app/api/rate_limit.py`, `app/api/play.py` (`_limited`, `start`, `submit`, `run_code`), `app/api/admin_auth.py` (`login_page`), `app/api/assets/countdown.js`, `app/settings.py` (`KVZ_*_PER_MINUTE`), `deploy/Caddyfile` (`X-Forwarded-For`, `keepalive`), `tests/api/test_request_limits.py`
- **Články:** view → `client_ip` (první hodnota `X-Forwarded-For`, kterou píše Caddy) → `rate_limit.allow(koš, klíč)` jako první věc view (`start` a `submit` počítají každý požadavek; `code` jen neúspěchy po kontrole) → `record`; přihlášení bere místo v koších `login` (jméno a adresa) a `login_address` (jen adresa) přes `try_acquire` před `authenticate()` a při správném přihlášení je vrací přes `release` → při překročení 429 s `Retry-After: 60` (fragment pro HTMX, jinak stránka; u přihlášení formulář s hláškou).
- **Odmítnutí:** šestý špatný login za minutu (i souběžný), 31. špatný login z jedné adresy přes různá jména, jedenáctý špatný kód, 121. odeslání a 301. start z jedné adresy; nová veřejná routa s POST bez deklarace koše nebo důvodu (`test_request_limits.py`).
- **Spuštění:** `uv run pytest tests/api/test_rate_limit.py tests/api/test_login_limit.py tests/api/test_play_limits.py tests/api/test_request_limits.py tests/api/test_access_code_flow.py tests/test_deploy_headers.py -q`
- **Mimo testy:** `make load` (zkouška adres: LAN zdroj se počítá zvlášť), průchod v prohlížeči: stránka 429 u přihlášení a u startu (v jazyce formuláře), vynucená 500 a 429 při automatickém odeslání s čekací hláškou.

## Denní záloha

- **Týká se:** `app/domain/backup.py`, `app/domain/management/commands/jobs.py` (`pass_once`, `keep_beating`), `app/domain/management/commands/backup.py`, `app/domain/heartbeat.py`, `app/api/heartbeat.py`, `deploy/compose.yaml` (svazek `backups` jen v `jobs`, healthcheck `jobs`), `Dockerfile` (`/data/backups`), `app/settings.py` (`KVZ_BACKUP_PATH`, `KVZ_BACKUP_RETENTION_DAYS`)
- **Články:** `jobs` každou hodinu `pass_once` → `retention.run_pass` (vlastní `try`) → `backup.due` (místní datum) → `create`: zámek, `.tmp-<datum>`, kopie databáze zálohovacím API, média (pevné odkazy na beze změny), `manifest.json` → `verify` (integrita, součty, migrace) → `fsync` → přejmenování na `YYYY-MM-DD` → `prune` po každém pokusu, i neúspěšném (nejnovější platná záloha zůstává; vrací `PruneResult`, zbylý adresář `jobs` zaloguje počtem a průchod zůstane `ok`, příkaz `backup` skončí chybou). `pass_once` zapisuje záznam průchodu (`ok` nebo `failed`), který čte healthcheck `jobs` a Historie mazání; tep `jobs` píše vlákno každých 15 s, tep `app` `HeartbeatMiddleware` nejvýš jednou za 10 s.
- **Odmítnutí:** databáze, která není soubor, kopie nad lhůtu, soubor jiný než v manifestu, migrace, které kód nezná (po přepnutí poskytovatele), druhá záloha zároveň. Selhání jde do logu jen typem.
- **Spuštění:** `uv run pytest tests/domain/test_backup.py tests/domain/test_jobs_backup.py tests/domain/test_heartbeat.py tests/domain/test_jobs_heartbeat.py tests/api/test_heartbeat_middleware.py tests/test_deploy_healthcheck.py -q`
- **Mimo testy:** `make smoke` (záloha při startu `jobs`, ruční záloha), `make load` (záloha během odesílání).

## Obnova ze zálohy

- **Týká se:** `app/domain/backup.py` (`resolve`, `restore`, `MARKER`), `app/domain/heartbeat.py`, `app/domain/management/commands/restore.py`, `deploy/load.sh` (čekání na tep), `deploy/compose.yaml`, `docs/deployment.md` (postup)
- **Články:** `docker compose -f deploy/compose.yaml stop caddy app jobs` → `docker compose run --rm --no-deps jobs python manage.py restore <datum|latest>` → `resolve` → zámek → odmítnutí, dokud existuje značka `pre-restore-*/.restoring` → `verify` → starší schéma → živá služba (tep `app` nebo `jobs` mladší než 60 s) → databáze v používání (`BEGIN EXCLUSIVE`, zbylý `-wal` nebo `-shm`) → kopie dosavadních dat do `pre-restore-<čas>` → značka `.restoring` → výměna obsahu databáze a médií kopiemi (nikdy odkazem) a vlastník uid 1000 → kontrola součtů → smazání značky; při chybě návrat původních dat a smazání značky, jen když se vrátila celá.
- **Odmítnutí:** poškozená záloha (`latest` se nevrací k starší), starší schéma, běžící `app` nebo `jobs`, databáze v používání, nedokončená dřívější obnova (značka), neznámé datum; neúspěch po kopii dat vrátí původní stav. `prune` označený adresář nikdy nesmaže.
- **Spuštění:** `uv run pytest tests/domain/test_restore.py tests/domain/test_backup.py -q`
- **Mimo testy:** `make smoke` (`restore latest`), `make load` (nácvik po změně živých dat; skript opakuje `restore latest` nejvýš 18krát po 5 s, jen dokud odmítnutí obsahuje „counts as stopped“), ruční obnova z `pre-restore-*` a odstranění značky podle `docs/deployment.md`.

## Zátěž (`make load`)

- **Týká se:** `deploy/load.sh`, `tools/load_participants.py`, `tests/integration/test_concurrent_submissions.py`, `tests/support/file_database.py`, `tests/support/server.py`, `deploy/Caddyfile`, `app/api/rate_limit.py`, `app/domain/backup.py`, `Makefile`
- **Články:** `make load` → projekt `kvizotron-load` → tři kvízy (`load` s fotkou, `reveal`, `probe`) → záloha v `jobs` běží po dobu odesílání → 50 klientů z jedné adresy: start, naráz odeslání s fotkou, opakování → okénko proti zálohám → počty a otisk z databáze, bez `database is locked` → průchod s odhalením → zkouška adres → záloha, změna živých dat, `restore latest`, porovnání → počet dotazů veřejné stránky.
- **Odmítnutí:** odpověď mimo 2xx včetně 429, jiný počet pokusů nebo fotek, záloha mimo okénko odesílání, obnova, která nevrátí původní otisk; bez adresy v LAN se zkouška adres neměří.
- **Spuštění:** `uv run pytest tests/integration/test_concurrent_submissions.py tests/test_load_participants.py tests/test_makefile.py -q`
- **Mimo testy:** `make load` (Docker, minuty); výstup patří do závěrečné zprávy milníku.
