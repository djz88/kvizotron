#!/bin/sh
# Spustí celé nasazení na lokálním stroji a ověří ho. Po sobě uklidí jen vlastní projekt.
set -u

PROJECT=kvizotron-smoke
HTTP_PORT=${SMOKE_HTTP_PORT:-18080}
HTTPS_PORT=${SMOKE_HTTPS_PORT:-18443}
FILE=deploy/compose.yaml
SECRET=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')

# Soubor deploy/.env provozovatele se sem nesmí dostat.
export COMPOSE_DISABLE_ENV_FILE=1
export KVZ_DOMAIN=localhost KVZ_SECRET_KEY="$SECRET" KVZ_HTTP_PORT="$HTTP_PORT" KVZ_HTTPS_PORT="$HTTPS_PORT"
compose() { docker compose -p "$PROJECT" -f "$FILE" "$@"; }

failed=0
check() { # check <name> <actual> <expected>
    if [ "$2" = "$3" ]; then
        echo "PASS $1"
    else
        echo "FAIL $1: got '$2', expected '$3'"
        failed=1
    fi
}
config_fails_naming() { # config_fails_naming <variable>
    output=$(env -u "$1" docker compose -p "$PROJECT" -f "$FILE" config 2>&1) && {
        echo "FAIL compose starts without $1"
        failed=1
        return
    }
    case "$output" in
        *"$1"*) echo "PASS compose refuses to start without $1" ;;
        *) echo "FAIL compose error does not name $1: $output"; failed=1 ;;
    esac
}

config_fails_naming KVZ_SECRET_KEY
config_fails_naming KVZ_DOMAIN

trap 'compose down -v --remove-orphans >/dev/null 2>&1' EXIT
if ! compose up --build --wait --wait-timeout 180 >/dev/null 2>&1; then
    echo "FAIL compose up"
    compose ps -a
    compose logs --tail 30
    exit 1
fi

body=$(curl -sk --resolve "localhost:$HTTPS_PORT:127.0.0.1" "https://localhost:$HTTPS_PORT/healthz")
check "healthz over HTTPS through Caddy" "$body" '{"status": "ok"}'

code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: localhost' "http://127.0.0.1:$HTTP_PORT/healthz")
check "plain HTTP redirects" "$code" "308"
location=$(curl -s -o /dev/null -w '%{redirect_url}' -H 'Host: localhost' "http://127.0.0.1:$HTTP_PORT/healthz")
case "$location" in
    https://*) echo "PASS redirect goes to HTTPS" ;;
    *) echo "FAIL redirect target: $location"; failed=1 ;;
esac

code=$(compose exec -T app python -c "
import urllib.error, urllib.request
req = urllib.request.Request('http://localhost:8000/healthz', headers={'Host': 'evil.example.net'})
try:
    print(urllib.request.urlopen(req).status)
except urllib.error.HTTPError as e:
    print(e.code)")
check "foreign Host rejected by the app" "$code" "400"

check "app is not root" "$(compose exec -T app id -u)" "1000"

mode=$(compose exec -T app python -c "
import os, sqlite3
print(sqlite3.connect(os.environ['KVZ_DB_PATH']).execute('PRAGMA journal_mode').fetchone()[0])")
check "database on volume uses WAL" "$mode" "wal"

workers=$(compose exec -T app python -c "
import glob, os
own = f'/proc/{os.getpid()}/cmdline'
print(sum('gunicorn' in open(p, 'rb').read().decode(errors='ignore') for p in glob.glob('/proc/[0-9]*/cmdline') if p != own))")
check "gunicorn master + one worker" "$workers" "2"

modules=$(compose exec -T app python manage.py modules list)
for module in auth.local persistence.sqlite; do
    case "$modules" in
        *"$module"*) echo "PASS module $module is active" ;;
        *) echo "FAIL module $module is not active: $modules"; failed=1 ;;
    esac
done

# Heslo jen přes stdin, generované pro tento běh; nikam se nevypisuje.
PASSWORD=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
init_admin() { printf '%s\n' "$PASSWORD" | compose exec -T app python manage.py init_admin smoke-admin --password-stdin >/dev/null 2>&1; echo $?; }
check "init_admin creates the first admin" "$(init_admin)" "0"
check "second init_admin is refused" "$(init_admin)" "1"

BASE="https://localhost:$HTTPS_PORT"
web() { curl -sk --resolve "localhost:$HTTPS_PORT:127.0.0.1" "$@"; }
status() { web -o /dev/null -w '%{http_code}' "$@"; }
field() { # field <name> <html>
    printf '%s' "$2" | sed -n "s/.*name=\"$1\" value=\"\([^\"]*\)\".*/\1/p" | head -n 1
}

for asset in m/theme.default/pico.min.css m/theme.default/theme.css assets/htmx.min.js assets/play.js; do
    check "$asset is served" "$(status "$BASE/$asset")" "200"
done
header=$(web -D - -o /dev/null "$BASE/" | tr -d '\r' | grep -i '^content-security-policy:')
case "$header" in
    *"default-src 'self'"*) echo "PASS CSP header is set" ;;
    *) echo "FAIL CSP header: $header"; failed=1 ;;
esac
check "admin needs login" "$(web -o /dev/null -w '%{redirect_url}' "$BASE/admin/quizzes")" "$BASE/admin/login?next=/admin/quizzes"

JAR=$(mktemp)
trap 'rm -f "$JAR"; compose down -v --remove-orphans >/dev/null 2>&1' EXIT
token=$(field csrfmiddlewaretoken "$(web -c "$JAR" "$BASE/admin/login")")
code=$(printf 'csrfmiddlewaretoken=%s&login=smoke-admin&password=%s' "$token" "$PASSWORD" |
    status -b "$JAR" -c "$JAR" -e "$BASE/admin/login" --data-binary @- "$BASE/admin/login")
check "admin logs in with the generated password" "$code" "302"
check "admin page opens after login" "$(status -b "$JAR" "$BASE/admin/quizzes")" "200"

quiz=$(compose exec -T app python manage.py shell -v 0 -c "
from app.domain import authoring
from app.domain.models import Quiz
from app.kernel.models import AdminUser
quiz = Quiz.objects.create(slug='smoke', title={'cs': 'Smoke'}, default_locale='cs', supported_locales=['cs'])
authoring.save_question(quiz, None, 'choice.single', {
    'prompt': {'cs': 'Otázka'},
    'options': [{'id': 'aaaa1111', 'text': {'cs': 'A'}}, {'id': 'bbbb2222', 'text': {'cs': 'B'}}],
    'correct': 'bbbb2222',
})
admin = str(AdminUser.objects.get().pk)
authoring.publish(quiz, admin_id=admin)
run = authoring.open_run(quiz, admin_id=admin)
print(run.id, run.current_revision.snapshot_json['questions'][0]['id'])
" | tail -n 1)
run_id=${quiz% *}
question=${quiz#* }
check "public quiz page" "$(status "$BASE/q/smoke")" "200"
check "round page for admin" "$(status -b "$JAR" "$BASE/admin/runs/$run_id")" "200"

started=$(web -X POST -e "$BASE/q/smoke" -d lang=cs "$BASE/r/$run_id/start")
case "$started" in
    *correct*) echo "FAIL start page reveals the answer key"; failed=1 ;;
    *Otázka*) echo "PASS start shows the question without the answer key" ;;
    *) echo "FAIL start: $started"; failed=1 ;;
esac
attempt=$(printf '%s' "$started" | sed -n 's|.*action="\(/a/[^"]*\)".*|\1|p' | head -n 1)
attempt_token=$(field attempt_token "$started")
key=$(field submission_key "$started")
submit() { web -X POST --data-urlencode "attempt_token=$attempt_token" -d "submission_key=$key" -d lang=cs -d "$question:option=bbbb2222" "$BASE$attempt"; }
first=$(submit)
case "$first" in
    *"1 / 1"*) echo "PASS server scores the attempt" ;;
    *) echo "FAIL score: $first"; failed=1 ;;
esac
check "second submit gives the same result" "$(submit)" "$first"

[ "$failed" -eq 0 ] && echo "SMOKE OK" || echo "SMOKE FAILED"
exit "$failed"
