# Module: tests

The structure mirrors `app/`. The rules for tests are in the root `CLAUDE.md`; here is how they are built.

## Where things are

- `contracts/`: suites that every module must pass. `question_type.py` is the base, `test_<type>.py` inherits it.
- `domain/`, `api/`, `kernel/`, `providers/`: tests of the individual layers.
- `integration/`: whole flows over HTTP and tests in a separate process.
- `test_docs.py`: IDs in the documentation, links, paths and the names of skills and of ACs that no test names; that list may only shrink (AC-01 to AC-18 are no longer in it), an AC that a test names must disappear from the list and a new AC needs a test with its ID in the docstring (`AC-129: …`). `test_request_limits.py` in `api/` requires a limit bucket or a reason for every public route with POST. `test_agent_hooks.py`: the hook against deleting volumes. `test_language.py`: no Czech sentence outside quotes, code and `cs`/`uk` table columns, and no Czech letter in build, deploy and tool files (the Language rule in the root `CLAUDE.md`). `test_wiring.py`: modules, templates, URLs, scripts, styles and settings are wired up.
- `support/`: `FormClient`, `run_manage`, `make_module`, `sheets_fake.py` (`SheetsFake` for the `table_sink` port, AC-109), `waiting` (`busy.py`: repeats a call while the shared test database is locked, where SQLite does not wait as it does in production). `file_database.py` (fixture `file_db`: a real SQLite file with the production schema and options, next to the in-memory database; use `sqlite3` or code with a path parameter, not the ORM). `server.py` (`running_server`: a real `gunicorn` as in production on a database file, an address for `urllib`; the log is `server.log` next to the database). `fixtures/`: sample modules and installations for AC-01 and AC-02.
- `domain/helpers.py`: builds quizzes through the same services as the administration.

## Watch out

- Submit through `FormClient` or the `client` fixture. A plain `django.test.Client` sends multipart and the application rejects it with 415.
- Publishing over HTTP needs `snapshot_hash` from the publish page. Through the service while a run is active it needs `decision`.
- A new test in `contracts/question_type.py` changes the count in `contracts/test_demo_question.py`.
- A new question type in `fixtures/demo_site` changes the count in `contracts/test_demo_question.py`.
- Send multipart with an image through a plain `Client` after `force_login` and set `settings.KVZ_MEDIA_PATH` to `tmp_path`.
- Tests see HTML, not the browser. The inheritance of HTMX attributes was revealed only by a walkthrough in the browser: verify a change to `hx-*` there too.

## Not here

Real login credentials and the network. Passwords in tests are test values; accepted scanner findings are in `docs/_architecture/security.md`.
