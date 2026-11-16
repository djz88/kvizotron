# Modul: app/plugins/participants

Plugin `participants.basic`, port `participant_policy`: čistá pravidla pro účastníka. Čte přezdívku a e-mail a rozhoduje, co se stane při startu pokusu (`on_start`, tabulka je v `docs/plugin-api.md`).

## Co modul obsahuje

`policy.py` (`BasicParticipantPolicy`), `manifest.py` s osmi nastaveními (`repeat_attempts`, `unfinished_attempt`, `max_attempts`, `after_pass`, `ask_name`, `ask_email`, `ask_when`, `duplicate_names`), `apps.py`. Rozsah nastavení je global a kvíz, protože platí pro celý pokus.

## Co modul není

Nesahá do databáze ani do požadavku. Nezná pokusy, běhy ani cookies: stav mu předá API (`finished`, `used`, `passed`, `open_attempt`; kontrakt 1.1, AC-173) a on vrátí rozhodnutí. Nastavení nečte, dostane `rules`.

## Zakázáno

Importovat z `app/domain`, `app/api` nebo z jiného pluginu: smí jen `app.contracts`. Zapisovat přezdívku nebo e-mail do logu.
