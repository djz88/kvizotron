#!/bin/sh
# Load test: 50 participants submit answers with a photo at once while a backup runs. Then it counts what is
# in the database, and the restore from a backup and the client addresses are tried. Cleans up only its own projects afterwards.
set -u

PROJECT=kvizotron-load
RESTORE_PROJECT=kvizotron-load-restore
HTTP_PORT=${LOAD_HTTP_PORT:-18280}
HTTPS_PORT=${LOAD_HTTPS_PORT:-18643}
CLIENTS=50
FILE=deploy/compose.yaml
SECRET=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')

# The operator's deploy/.env file must not get in here.
export COMPOSE_DISABLE_ENV_FILE=1
# Limits and backup retention from the operator's environment would reach the test
# deployment through compose, and 50 clients from one address would get 429.
unset KVZ_LOGIN_ATTEMPTS_PER_MINUTE KVZ_CODE_ATTEMPTS_PER_MINUTE KVZ_SUBMITS_PER_MINUTE \
    KVZ_STARTS_PER_MINUTE KVZ_LOGIN_ADDRESS_ATTEMPTS_PER_MINUTE KVZ_BACKUP_RETENTION_DAYS
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

WORK=$(mktemp -d)
backup_pid=""
# The second project is not created (the restore runs in this one); cleanup knows it only to be safe. Only
# `kvizotron-load` and `kvizotron-load-restore` are deleted, never a foreign project.
cleanup() {
    [ -n "$backup_pid" ] && kill "$backup_pid" 2>/dev/null
    rm -rf "$WORK"
    compose down -v --remove-orphans >/dev/null 2>&1
    docker compose -p "$RESTORE_PROJECT" -f "$FILE" down -v --remove-orphans >/dev/null 2>&1
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! compose up --build --wait --wait-timeout 180 >/dev/null 2>&1; then
    echo "FAIL compose up"
    compose ps -a
    compose logs --tail 30
    exit 1
fi

# A quiz with a choice question and a photo, one question per page, reveal at the end with everything (a person has to
# grade the photo, so the application refuses reveal after each question for a quiz with a photo; `check` is
# tried only on the `reveal` quiz without a photo), data profile with answers. The `reveal` quiz has no photo and reveals after each question; the `probe` quiz is only for the address check (every start makes an attempt).
seeded=$(compose exec -T app python manage.py shell -v 0 -c '
from app.domain import authoring
from app.domain import settings as app_settings
from app.domain.models import Quiz

def seed(slug, photo, moment):
    quiz = Quiz.objects.create(slug=slug, title={"cs": slug}, description={"cs": slug},
                               default_locale="cs", supported_locales=["cs"])
    authoring.save_question(quiz, None, "choice", {
        "prompt": {"cs": "Otázka"},
        "options": [{"id": "aaaa1111", "text": {"cs": "A"}}, {"id": "bbbb2222", "text": {"cs": "B"}}],
        "correct": ["bbbb2222"],
    })
    if photo:
        authoring.save_question(quiz, None, "image_answer", {
            "prompt": {"cs": "Vyfoťte"}, "auto": {"right": 2, "total": 10}}, points=10, scoring="partial")
    app_settings.set_override(app_settings.NAVIGATION_MODE, quiz, "step_back", admin_id=None)
    app_settings.set_override(app_settings.REVEAL_MOMENT, quiz, moment, admin_id=None)
    app_settings.set_override(app_settings.REVEAL_LEVEL, quiz, "explanations", admin_id=None)
    authoring.publish(quiz, admin_id="load-seed")
    return authoring.open_run(quiz, admin_id="load-seed", data={"profile": "answers"})

print(seed("load", True, "at_end").id, seed("reveal", False, "after_each").id, seed("probe", False, "never").id)
' | tail -n 1 | tr -d '\r')
# Exactly three distinct run ids.
# shellcheck disable=SC2086
set -- $seeded
distinct=$(printf '%s\n' "$@" | sort -u | grep -Ec '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
if [ "$#" -ne 3 ] || [ "$distinct" -ne 3 ]; then
    echo "FAIL seed did not return three distinct run ids: '$seeded'"
    compose logs --tail 30 app
    exit 1
fi
run_id=$1
reveal_run=$2
probe_run=$3
echo "INFO runs: load $run_id, reveal $reveal_run, probe $probe_run"

# What is in the database: counts for the run and a fingerprint of all attempts, answers, files and photos.
snapshot() { # snapshot <run>
    compose exec -T app python manage.py shell -v 0 -c "
import hashlib, os
from django.conf import settings
from app.domain.models import Attempt, AttemptAnswer
from app.providers.media_local.models import MediaAsset
mine = Attempt.objects.filter(run_id='$1')
answers = AttemptAnswer.objects.filter(attempt__run_id='$1', asset_id__isnull=False)
root = settings.KVZ_MEDIA_PATH
files = sorted(
    (os.path.relpath(os.path.join(d, f), root), hashlib.sha256(open(os.path.join(d, f), 'rb').read()).hexdigest())
    for d, _dirs, names in os.walk(root) for f in names)
digest = hashlib.sha256(repr((
    list(Attempt.objects.order_by('id').values_list('id', 'status', 'submission_key', 'score')),
    list(AttemptAnswer.objects.order_by('attempt_id', 'question_id').values_list(
        'attempt_id', 'question_id', 'asset_id', 'auto_points')),
    list(MediaAsset.objects.order_by('id').values_list('id', 'storage_key', 'sha256')),
    files)).encode()).hexdigest()
print('total=%d finished=%d keys=%d photo_answers=%d distinct_photos=%d private_assets=%d files=%d' % (
    mine.count(),
    mine.filter(status__in=Attempt.FINISHED).count(),
    mine.exclude(submission_key=None).values('submission_key').distinct().count(),
    answers.count(),
    answers.values('asset_id').distinct().count(),
    MediaAsset.objects.filter(private=True).count(),
    len(files)))
print('checksum', digest)
" | tr -d '\r' | tail -n 2
}
expected="total=$CLIENTS finished=$CLIENTS keys=$CLIENTS photo_answers=$CLIENTS distinct_photos=$CLIENTS private_assets=$CLIENTS files=$CLIENTS"

BASE="https://localhost:$HTTPS_PORT"

# A real photo (1600x1200 noise, about 700 kB), made by Pillow in the container: decoding and conversion to
# WebP cost the server the most. The file is in a temporary directory on the host.
compose exec -T app python -c "
import os, sys
from PIL import Image
image = Image.frombytes('RGB', (360, 270), os.urandom(360 * 270 * 3)).resize((1600, 1200), Image.BICUBIC)
image.save(sys.stdout.buffer, 'JPEG', quality=85)" >"$WORK/photo.jpg" 2>/dev/null
photo_bytes=$(wc -c <"$WORK/photo.jpg")
if [ "$photo_bytes" -lt 100000 ]; then
    echo "FAIL could not make the photo ($photo_bytes bytes)"
    exit 1
fi

# Backups run in one long process in `jobs` for the whole submission: each call prints
# its start and end (epoch) so that overlap with the submission window can be verified. A backup of the same day
# replaces the previous one. The file /tmp/load-stop stops it, otherwise it stops by itself after 150 s.
loop=$(cat <<'EOF'
import os, time
from django.utils import timezone
from app.domain import backup
deadline = time.time() + 150
while not os.path.exists("/tmp/load-stop") and time.time() < deadline:
    began = time.time()
    try:
        backup.create(timezone.now())
        result = "ok"
    except backup.BackupError:
        result = "failed"
    print("start=%.3f end=%.3f %s" % (began, time.time(), result), flush=True)
    time.sleep(0.05)
EOF
)
compose exec -T jobs python manage.py shell -v 0 -c "$loop" >"$WORK/backups" 2>&1 &
backup_pid=$!
for _ in $(seq 1 60); do
    grep -q '^start=' "$WORK/backups" && break
    sleep 1
done

python3 -m tools.load_participants --base "$BASE" --run "$run_id" --clients "$CLIENTS" \
    --photo-file "$WORK/photo.jpg" >"$WORK/participants" 2>&1
participants_code=$?
compose exec -T jobs touch /tmp/load-stop >/dev/null 2>&1
wait "$backup_pid"
backup_pid=""
cat "$WORK/participants"
[ "$participants_code" -eq 0 ] || failed=1

# Submission window against backups: at least one backup call must run in the window and none may fail.
window=$(grep '^WINDOW ' "$WORK/participants")
first=${window#*first=}; first=${first%% *}
last=${window##*last=}
calls=$(grep -c '^start=' "$WORK/backups")
missed=$(grep -c '^start=.* failed$' "$WORK/backups")
overlap=$(awk -v f="${first:-0}" -v l="${last:-0}" '/^start=/ { split($1, a, "="); split($2, b, "="); if (a[2] <= l && b[2] >= f) n++ } END { print n + 0 }' "$WORK/backups")
inside=$(awk -v f="${first:-0}" -v l="${last:-0}" '/^start=/ { split($1, a, "="); split($2, b, "="); if (a[2] >= f && b[2] <= l) n++ } END { print n + 0 }' "$WORK/backups")
echo "INFO submit window $first .. $last, $calls backup calls, $overlap overlap the window, $inside lie inside it, $missed failed"
check "a backup call ran during the submissions (window found, overlapping calls>0)" "$([ -n "$window" ] && [ "$overlap" -gt 0 ] && echo yes)" "yes"
check "every backup call finished ok (calls>0, failed)" "$([ "$calls" -gt 0 ] && echo yes)/$missed" "yes/0"

counts=$(snapshot "$run_id" | head -n 1)
check "database holds each attempt, key and photo exactly once" "$counts" "$expected"
logs=$(compose logs app 2>&1)
check "app log has no 'database is locked'" "$(printf '%s\n' "$logs" | grep -c 'database is locked')" "0"
check "app log has no traceback" "$(printf '%s\n' "$logs" | grep -c Traceback)" "0"

# Reveal after each question: the page calls `check` before submitting (quiz without a photo, 20 participants).
python3 -m tools.load_participants --base "$BASE" --run "$reveal_run" --clients 20 || failed=1
logs=$(compose logs app 2>&1)
check "app log has no traceback after the reveal pass" "$(printf '%s\n' "$logs" | grep -c Traceback)" "0"

# Address check: does the application separate source addresses (the start limit is per address)?
unmeasured=0
lan=$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -v '^127\.' | grep -m 1 '^[0-9]*\.[0-9]*\.[0-9]*\.[0-9]*$')
limit=$(compose exec -T app python manage.py shell -v 0 -c "
from django.conf import settings
print(settings.KVZ_STARTS_PER_MINUTE)" | tail -n 1 | tr -d '\r')
if [ -z "$lan" ]; then
    echo "NOT MEASURED address probe: no LAN address"
    unmeasured=1
else
    python3 -m tools.load_participants --base "$BASE" --run "$probe_run" --clients 1 \
        --probe-from "$lan" --probe-limit "$limit" || failed=1
fi

# Restore rehearsal. First a fresh backup of everything now in the database. Then the live data is CHANGED (the attempts
# of the run and one media file are deleted), it is verified that the fingerprint changed, and only then is it restored. A restore
# that does nothing would not pass.
complete='^(total=.* files=[0-9]+|checksum [0-9a-f]{64})$'
before=$(snapshot "$run_id")
check "snapshot before the restore is complete" "$(printf '%s\n' "$before" | grep -Ec "$complete")" "2"
compose exec -T jobs python manage.py backup >/dev/null 2>&1
check "final backup exits 0" "$?" "0"
mutated=$(compose exec -T app python manage.py shell -v 0 -c "
import os
from django.conf import settings
from app.domain.models import Attempt
deleted = Attempt.objects.filter(run_id='$run_id').delete()[0]
removed = 0
for d, _dirs, names in os.walk(settings.KVZ_MEDIA_PATH):
    for f in sorted(names):
        os.remove(os.path.join(d, f))
        removed += 1
        break
    if removed:
        break
print('deleted rows=%d media files=%d' % (deleted, removed))
" | tail -n 1 | tr -d '\r')
echo "INFO live data changed before the restore: $mutated"
changed=$(snapshot "$run_id")
check "snapshot differs after the live data was changed" "$([ "$changed" != "$before" ] && printf '%s\n' "$changed" | grep -Ec "$complete")" "2"
compose stop app jobs >/dev/null 2>&1
# A stopped service may still hold a young heartbeat file (app removes its file at exit when it can,
# jobs on a clean stop), and the restore refuses until it counts as stopped, after at most 60 s.
# Retry only while the refusal is that one (its fixed phrase); any other failure ends the wait.
for _ in $(seq 1 18); do
    restore_output=$(compose run --rm --no-deps jobs python manage.py restore latest 2>&1)
    restore_code=$?
    [ "$restore_code" -ne 0 ] || break
    printf '%s\n' "$restore_output" | grep -q 'counts as stopped' || break
    sleep 5
done
check "restore latest exits 0" "$restore_code" "0"
[ "$restore_code" -eq 0 ] || echo "$restore_output"
compose start app jobs >/dev/null 2>&1
body=""
for _ in $(seq 1 60); do
    body=$(curl -sk --resolve "localhost:$HTTPS_PORT:127.0.0.1" "$BASE/healthz")
    [ "$body" = '{"status": "ok"}' ] && break
    sleep 1
done
check "healthz answers again after the restore" "$body" '{"status": "ok"}'
after=$(snapshot "$run_id")
check "snapshot after the restore is complete" "$(printf '%s\n' "$after" | grep -Ec "$complete")" "2"
check "counts after the restore equal the counts before" "$(printf '%s\n' "$after" | head -n 1)" "$(printf '%s\n' "$before" | head -n 1)"
check "checksum of attempts, answers and photo contents after the restore equals the one before" "$(printf '%s\n' "$after" | tail -n 1)" "$(printf '%s\n' "$before" | tail -n 1)"

# Evidence for TD-056: number of database queries per public quiz page (cold and warmed up).
queries=$(compose exec -T app python manage.py shell -v 0 -c "
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
client = Client()
counts = []
for _ in range(2):
    with CaptureQueriesContext(connection) as captured:
        status = client.get('/q/load', HTTP_HOST='localhost', secure=True).status_code
    counts.append('%d (HTTP %d)' % (len(captured), status))
print(' then '.join(counts))
" | tail -n 1 | tr -d '\r')
echo "INFO queries per public quiz page: $queries"

if [ "$failed" -ne 0 ]; then
    echo "--- end of the app and Caddy logs"
    compose logs --tail 40 app caddy 2>&1
    echo "LOAD FAILED"
elif [ "$unmeasured" -ne 0 ]; then
    echo "LOAD OK (address not measured)"
else
    echo "LOAD OK"
fi
exit "$failed"
