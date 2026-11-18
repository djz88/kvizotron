# Module: tools

Helper scripts for development, called from the `Makefile`. They do not go into the image and the application does not import them.

## Responsibilities

- `messages.py`: `make messages`. Extracts texts and compiles the catalogs from `ROOTS`.
- `tech_debt.py`: `make tech-debt-*`. Works with `docs/_architecture/TECH_DEBT.md` and the archive.
- `plan_check.py`: `make plan-check`. Compares the files named in a plan with git.
- `private_traces.py`: the `private-traces*` hooks from `.pre-commit-config.yaml` (commit, commit message, push). Rejects the home directory, the agent's temporary directory, a link to an agent session and words from the list `.git/info/private-traces`, which is outside git (a name, a home-network address, an e-mail; one per line, `#` is a comment). It finds the list through `git rev-parse --git-common-dir`, so a worktree shares the list of the main checkout. Without the list the hooks pass with a reminder; `list` (from `make hooks` and `make doctor`) reports whether it exists and `make private-traces` creates it empty. A line `allow TEXT [PATH…]` in the same list is an exception, not a word: a finding inside TEXT passes only in the named files (path from the repository root), without a path everywhere; the commit message takes only the exceptions for everywhere, push judges them per file. It serves the owner in `.github/CODEOWNERS` and `SECURITY.md`; a bare word elsewhere still does not pass.
- `load_deadline.py`: a load test of submission at one moment (AC-07).
- `load_participants.py`: `make load` (together with `deploy/load.sh`). 50 participants start, call `check` where the page wants it, and then submit the form with a photo all at once (`--photo-file`: a real image, `make load` makes it with Pillow in the container, about 700 kB; without it a JPEG assembled without Pillow from a small image and padding, which tests only the upload, not the decoding); one `PASS`/`FAIL`/`INFO` line per criterion (2xx, the same result on repeated submission, the slowest under 5 s) and a `WINDOW first=… last=…` line with the submission window. With `--probe-from ADDRESS` it tests whether the application counts the start limit separately for different sources (a LAN address against loopback 127.0.0.x; it cannot tell 127.0.0.1 and 127.0.0.2 apart). What only the database or the log knows (each attempt and photo once, the lock, the overlap of backups with the window, restore from a backup after a change of live data, the number of page queries) is checked by `deploy/load.sh` through `docker compose exec`; it runs only in the `kvizotron-load` project on the ports `LOAD_HTTP_PORT` and `LOAD_HTTPS_PORT`.

## Forbidden

- `load_participants.py`, `tech_debt.py`, `plan_check.py` and `private_traces.py` depending on anything outside the standard library: they run through `python3` without `uv`.
- Rewriting `.po` by hand outside `msgstr`: `make messages` regenerates them.
