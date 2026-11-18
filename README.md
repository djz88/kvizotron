Česky: [README.cs.md](README.cs.md)

# Kvízotron

"Switch on your brain. Start Kvízotron."

A self-hosted platform for multilingual quizzes (cs/en/uk) and competitions. The public plays without registration via a URL or a QR code. Local admins create quizzes, start competitive runs with a leaderboard and rewards, and carry out auditable drawings.

**Status:** all stages A to D are done. An admin writes a quiz in cs/en/uk (question types Choice, Matching, Number, Text and Photo), publishes it and opens a run with a QR code; a participant plays without registration and the server computes the score. A running quiz can be changed safely. This comes with leaderboards, rewards and drawings, results export, deleting data after the retention period, module management, request limits, a daily backup with a manual restore and a load test of 50 participants. The application is also meant for public deployment, but only in the Compose topology with Caddy and a single application process ([deployment](docs/deployment.md)). Before version 1.0, the release checks and the triage of technical debt remain.

## Documentation

- [Architecture](docs/_architecture/README.md) — start here
- [Roadmap](docs/_architecture/roadmap.md)
- [Decisions (ADR)](docs/_architecture/adr/README.md)
- [Plugin API](docs/plugin-api.md), [deployment](docs/deployment.md), [configuration](docs/configuration.md), [privacy](docs/privacy.md)

## Installation and use

Trying it out in Docker on your own machine:

```sh
export KVZ_DOMAIN=localhost KVZ_SECRET_KEY=$(openssl rand -hex 32) KVZ_HTTP_PORT=18080 KVZ_HTTPS_PORT=18443
docker compose -f deploy/compose.yaml up --build -d --wait
docker compose -f deploy/compose.yaml run --rm -it app python manage.py init_admin admin
```

Then open <https://localhost:18443/admin/login>. The browser will warn about Caddy's local certificate. Keep `KVZ_SECRET_KEY` for the next start, otherwise logins and attempts in progress stop being valid.

Production deployment is described in [docs/deployment.md](docs/deployment.md).

## Development

- `make help` — list of targets
- `make env-update` — installs the tool versions the project declares (uv, Python and packages, pre-commit with hooks, Docker images)
- `make setup` — installs dependencies (requires uv from `pyproject.toml`, see `make env-update`)
- `make hooks` — installs git hooks for commit, commit message and push: gitleaks and a check for local traces (`tools/private_traces.py`: home directory, the agent's temporary directories, links to an agent session)
- `make private-traces` — creates an empty `.git/info/private-traces`, where everyone writes their own personal words (name, home network address, e-mail; one per line; the exception `allow TEXT [PATH…]` allows a text only in the given files, without a path everywhere). The file is in `.git/`, so git never commits or pushes it; without it the hooks do not check personal words and remind you of it
- `make lint`, `make test`, `make secrets` — the individual checks
- `make quality` — all checks; the same runs in CI
- `make smoke` — verifies the whole deployment in Docker
- `make load` — load test in Docker: 50 participants with photos, a backup, a restore and an address check
- `make messages` — extracts texts for translation and compiles the catalogs

## License

[GNU GPL](LICENSE). Report security problems according to [SECURITY.md](SECURITY.md).
