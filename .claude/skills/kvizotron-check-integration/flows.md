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
- **Články:** `/admin/quizzes/<id>/plan` → `run_schedule.plan` → první požadavek po termínu a `settle` → otevřený běh → start s limitem → odpočet a `/a/<id>/time` → automatické odeslání → čas příjmu při `submit` → uzavření a počet neodeslaných → archiv.
- **Odmítnutí:** start před termínem, odeslání po limitu, pozdní fotka, nesplněné požadavky při otevření.
- **Spuštění:** `uv run pytest tests/api/test_run_plan.py tests/api/test_planned_quiz.py tests/api/test_run_deadline.py tests/api/test_countdown.py tests/api/test_run_archive.py tests/domain/test_run_schedule.py tests/domain/test_attempt_time.py tests/domain/test_clock.py -q`
- **Mimo testy:** `tools/load_deadline.py` při změně cesty odeslání, skutečné odeslání v prohlížeči přes `kvizotron-browser-walkthrough`.

## Účastníci a přístupový kód

- **Týká se:** `app/plugins/participants/`, `app/domain/participants.py`, `app/domain/access_codes.py`, `app/api/code_limit.py`, `app/api/play.py`, `app/api/public.py`, `app/api/admin_runs.py`, `app/api/jinja2/public/_identity_fields.html`
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

- **Týká se:** `app/plugins/results/`, `app/domain/results.py`, `app/domain/run_stats.py`, `app/domain/participants.py` (`needs_participant`, `attempt_rows`), `app/api/scoreboard.py`, `app/api/play.py`, `app/api/public.py`, `app/api/admin_runs.py`, `app/api/assets/scoreboard.js`, `app/api/jinja2/public/scoreboard.html`, `app/api/jinja2/public/_scoreboard_rows.html`
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

- **Týká se:** `app/api/admin_view.py`, `app/api/admin_settings.py`, `app/api/admin_quizzes.py` (`settings_page`), `app/api/admin_runs.py` (`_plan_page`), `app/api/jinja2/admin/_setting_groups.html`, `admin/base.html`, `_quiz_header.html`, `run.html`, `app/domain/settings.py` (`group`, `level`), manifesty modulů
- **Články:** `group` a `level` u nastavení → `group_fields` podle cookie `kvz_admin_view` a toho, co se liší od zděděné hodnoty → skupiny na stránce → POST bez skrytých polí → uložení, které prázdnou hodnotu bere jako beze změny.
- **Odmítnutí:** konflikt na skrytém poli ukáže pole i chybu; cizí `next` u přepínače vede na `/admin/`.
- **Spuštění:** `uv run pytest tests/domain/test_setting_groups.py tests/api/test_admin_view.py tests/api/test_run_plan.py tests/api/test_admin_layout.py tests/api/test_admin_settings.py -q`
- **Mimo testy:** průchod v prohlížeči: obě zobrazení, plán, „Více“ na telefonu, klávesnice.
