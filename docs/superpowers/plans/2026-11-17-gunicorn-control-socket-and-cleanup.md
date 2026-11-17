# Gunicorn control socket and cleanup after review

**Goal:** no "Control server error: Permission denied" on start; leftovers of review stacks removed.
**Constraint:** stacks `kvizotron-browser` and `kvizotron-tmp` are not touched by any step.

## 1. Gunicorn without a control socket

gunicorn 26 opens a control socket under `$HOME/.gunicorn/`; the image user `kvizotron` has no home
(`useradd --no-create-home`), so every start logs an error. Nothing uses the socket.

- [x] Failing test in `tests/domain/test_serve.py`: `IMAGE_COMMAND` holds `--no-control-socket`,
      (the equality of `CMD` and `serve.IMAGE_COMMAND` is already tested).
- [x] `--no-control-socket` in `IMAGE_COMMAND` (`app/domain/management/commands/serve.py`),
      and in `CMD` (`Dockerfile`); the test server (`tests/support/server.py`) has it already.
- [x] One sentence in `docs/deployment.md` and ADR-0066.
- [x] `make lint`, `make test`, `make smoke` (project `kvizotron-smoke` only); its app log holds
      no "Control server error".

## 2. Caddy of `kvizotron-tmp`

Done by the user, not the agent:
`docker compose -p kvizotron-tmp -f deploy/compose.yaml up -d --force-recreate --no-deps caddy`
(same environment as the build).

## 3. Cleanup

- [x] Stack `kvizotron-review`: containers `kvizotron-review-{app,caddy,jobs,migrate}-1`, volumes
      `kvizotron-review_{backups,caddy_config,caddy_data,db,media}`, network
      `kvizotron-review_default`; each removed by exact name only after its label
      `com.docker.compose.project` reads `kvizotron-review`.
- [x] `.worktrees/logo-families`, `.worktrees/combined-boards` (root-owned leftovers of Docker
      bind mounts): the user runs `sudo rm -r` on them.

No commit until the user asks.
