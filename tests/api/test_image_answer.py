"""A photo from a participant, from the form to storage (AC-55, AC-57, AC-61)."""

from datetime import timedelta
from pathlib import Path

import pytest
from django.test import Client
from django.test.client import MULTIPART_CONTENT
from django.utils import timezone

from app.contracts import ImageRefused
from app.domain import attempts, authoring, run_links, settings
from app.domain.models import Attempt, AttemptAnswer
from app.providers.media_local.models import MediaAsset
from app.providers.media_local.provider import LocalMediaStorage
from tests.domain.helpers import (
    ADMIN_ID,
    OPTION_A,
    add_bank_question,
    add_question,
    add_row,
    make_bank,
    make_quiz,
)
from tests.support.clock import freeze
from tests.support.photos import (
    Player,
    add_photo,
    field,
    jpeg,
    photo_config,
    photo_quiz,
    run_of,
    upload,
)

pytestmark = pytest.mark.django_db
PHOTO = "photo"


@pytest.fixture(autouse=True)
def media(tmp_path, settings):
    settings.KVZ_MEDIA_PATH = str(tmp_path)
    return tmp_path


def text(response):
    return response.content.decode()


def test_public_media_answers_404_for_a_participant_photo():
    player = Player(run_of(photo_quiz()))
    player.submit({f"{player.question('image_answer')}:image": upload()})
    asset = AttemptAnswer.objects.get().asset_id
    assert MediaAsset.objects.get(pk=asset).private is True
    assert Client().get(f"/media/{asset}").status_code == 404


def test_multipart_refused_on_submit_of_an_attempt_without_this_type():
    quiz = make_quiz()
    add_question(quiz)
    player = Player(run_of(quiz))
    assert player.submit({"x": upload()}).status_code == 415


def test_multipart_refused_for_an_attempt_that_does_not_exist():
    response = Client().post("/a/00000000-0000-7000-8000-000000000001/submit", {"x": upload()})
    assert response.status_code == 415


def test_multipart_refused_long_after_the_run_ended(monkeypatch):
    run = run_of(photo_quiz())
    player = Player(run)
    authoring.close_run(run, admin_id=ADMIN_ID)
    freeze(monkeypatch, timezone.now() + timedelta(minutes=11))
    assert player.submit({"x": upload()}).status_code == 415


def test_a_repeat_of_a_finished_attempt_gets_its_result_and_stores_nothing():
    player = Player(run_of(photo_quiz()))
    fields = {f"{player.question('image_answer')}:image": upload()}
    assert player.submit(fields).status_code == 200
    again = player.submit({f"{player.question('image_answer')}:image": upload()})
    assert again.status_code == 200 and MediaAsset.objects.count() == 1
    assert AttemptAnswer.objects.count() == 1


def test_multipart_refused_on_the_other_public_routes():
    run = run_of(photo_quiz())
    player = Player(run)
    assert Client().post(f"/r/{run.id}/start", {"x": upload()}).status_code == 415
    assert player.client.post(f"/a/{player.attempt.id}/switch", {"x": "1"}).status_code == 415
    assert player.client.post(f"/a/{player.attempt.id}/check", {"x": "1"}).status_code == 415


def test_multipart_form_has_encoding_only_when_needed():
    player = Player(run_of(photo_quiz()))
    assert 'enctype="multipart/form-data"' in player.html
    assert 'hx-encoding="multipart/form-data"' in player.html
    quiz = make_quiz(slug="plain")
    add_question(quiz)
    plain = Player(run_of(quiz))
    assert "multipart" not in plain.html


def test_submit_with_photo_shows_two_of_ten_pending():
    player = Player(run_of(photo_quiz()))
    html = text(player.submit({f"{player.question('image_answer')}:image": upload()}))
    player.attempt.refresh_from_db()
    assert player.attempt.status == Attempt.Status.PENDING_GRADING
    assert player.attempt.score == 2 and player.attempt.max_score == 10
    assert "předběžné" in html


def test_submit_without_photo_is_zero_and_nothing_waits():
    player = Player(run_of(photo_quiz()))
    html = text(player.plain())
    player.attempt.refresh_from_db()
    assert player.attempt.status == Attempt.Status.SUBMITTED and player.attempt.score == 0
    assert "předběžné" not in html and AttemptAnswer.objects.count() == 0


def test_empty_file_input_is_no_answer():
    player = Player(run_of(photo_quiz()))
    question = player.question("image_answer")
    form = player.form()
    parts = [
        f'--x\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        for name, value in form.items()
    ]
    parts.append(
        f'--x\r\nContent-Disposition: form-data; name="{question}:image"; filename=""\r\n'
        "Content-Type: application/octet-stream\r\n\r\n\r\n--x--\r\n"
    )
    response = player.client.generic(
        "POST",
        f"/a/{player.attempt.id}/submit",
        "".join(parts).encode(),
        content_type="multipart/form-data; boundary=x",
    )
    assert response.status_code == 200
    assert AttemptAnswer.objects.count() == 0
    assert MediaAsset.objects.count() == 0


def test_refused_file_keeps_other_answers_without_script():
    player = Player(run_of(photo_quiz(plain=True)))
    photo = player.question("image_answer")
    choice = player.question("choice")
    response = player.submit(
        {f"{photo}:image": upload(b"not a picture"), f"{choice}:options[]": [OPTION_A]}
    )
    assert response.status_code == 400
    html = text(response)
    assert f'value="{OPTION_A}" checked' in html and "attempt_token" in html
    assert "<p" in html and MediaAsset.objects.count() == 0
    player.attempt.refresh_from_db()
    assert player.attempt.status == Attempt.Status.IN_PROGRESS


def test_refused_file_with_htmx_answers_in_the_message_area():
    player = Player(run_of(photo_quiz()))
    response = player.submit(
        {f"{player.question('image_answer')}:image": upload(b"not a picture")},
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 400 and response["HX-Retarget"] == "#play-message"


def test_second_file_refused_removes_the_first():
    quiz = photo_quiz()
    add_photo(quiz)
    player = Player(run_of(quiz))
    first, second = [q["id"] for q in player.questions]
    response = player.submit(
        {f"{first}:image": upload(), f"{second}:image": upload(b"not a picture")}
    )
    assert response.status_code == 400 and MediaAsset.objects.count() == 0


def test_forged_image_field_is_ignored():
    """Review Focus 1: someone's asset id gives no points and no reach to it."""
    victim = Player(run_of(photo_quiz()))
    victim.submit({f"{victim.question('image_answer')}:image": upload()})
    asset = AttemptAnswer.objects.get().asset_id
    run = victim.attempt.run
    forger = Player(run)
    question = forger.question("image_answer")
    assert forger.plain({f"{question}:image": asset}).status_code == 200
    forger.attempt.refresh_from_db()
    assert forger.attempt.score == 0 and forger.attempt.status == Attempt.Status.SUBMITTED
    assert AttemptAnswer.objects.filter(attempt=forger.attempt).count() == 0


def test_forged_field_with_a_real_file_uses_only_the_file():
    player = Player(run_of(photo_quiz()))
    question = player.question("image_answer")
    fields = player.form()
    fields[f"{question}:image"] = "0" * 32
    response = player.client.post(
        f"/a/{player.attempt.id}/submit",
        fields | {f"{question}:image": ["0" * 32, upload()]},
    )
    assert response.status_code == 200
    row = AttemptAnswer.objects.get()
    assert row.asset_id != "0" * 32 and MediaAsset.objects.filter(pk=row.asset_id).exists()


def test_invalid_token_stores_nothing():
    player = Player(run_of(photo_quiz()))
    fields = player.form(**{f"{player.question('image_answer')}:image": upload()})
    fields["attempt_token"] = "forged"
    assert player.client.post(f"/a/{player.attempt.id}/submit", fields).status_code == 403
    assert MediaAsset.objects.count() == 0


def test_double_submit_one_result_loser_file_removed(monkeypatch):
    """Review Focus 4: the other request won while this one stored its file."""
    player = Player(run_of(photo_quiz()))
    question = player.question("image_answer")
    real = attempts.submit
    other = None

    def after_a_rival(attempt_id, token, answers, key, **kwargs):
        nonlocal other
        if other is None:
            other = LocalMediaStorage().store_participant_image(jpeg(), run_assets=[])
            real(attempt_id, token, {question: {"image": other}}, key)
        return real(attempt_id, token, answers, key, **kwargs)

    monkeypatch.setattr(attempts, "submit", after_a_rival)
    assert player.submit({f"{question}:image": upload()}).status_code == 200
    assert list(MediaAsset.objects.values_list("id", flat=True).order_by()) != []
    assert MediaAsset.objects.count() == 1
    assert AttemptAnswer.objects.get().asset_id == other


def test_failed_submit_removes_the_stored_file(monkeypatch):
    player = Player(run_of(photo_quiz()))

    def fail(*args, **kwargs):
        raise attempts.AttemptError("run_closed")

    monkeypatch.setattr(attempts, "submit", fail)
    assert player.submit({f"{player.question('image_answer')}:image": upload()}).status_code == 409
    assert MediaAsset.objects.count() == 0


def test_error_while_saving_removes_the_stored_file(monkeypatch):
    player = Player(run_of(photo_quiz()))

    def fail(*args, **kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(attempts, "submit", fail)
    player.client.raise_request_exception = False
    assert player.submit({f"{player.question('image_answer')}:image": upload()}).status_code == 500
    assert MediaAsset.objects.count() == 0


def test_run_limit_is_a_message_keeping_the_form(monkeypatch):
    def refuse(self, data, *, run_assets):
        raise ImageRefused("Tento běh už nepojme další fotky.")

    monkeypatch.setattr(LocalMediaStorage, "store_participant_image", refuse)
    player = Player(run_of(photo_quiz()))
    response = player.submit({f"{player.question('image_answer')}:image": upload()})
    assert response.status_code == 400 and "nepojme" in text(response)


def test_preview_reads_the_file_and_stores_nothing(logged_in):
    quiz = photo_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview"))
    assert 'enctype="multipart/form-data"' in html
    question = authoring.editable_questions(quiz)[0]["id"]
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/preview/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": "",
            "lang": "cs",
            f"{question}:image": upload(),
        },
        content_type=MULTIPART_CONTENT,
    )
    assert response.status_code == 200
    assert "předběžné" in text(response)
    assert MediaAsset.objects.count() == 0 and Attempt.objects.count() == 0


def test_preview_refuses_what_a_run_refuses(logged_in):
    quiz = photo_quiz()
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview"))
    question = authoring.editable_questions(quiz)[0]["id"]
    response = logged_in.post(
        f"/admin/quizzes/{quiz.id}/preview/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": "",
            "lang": "cs",
            f"{question}:image": upload(b"not a picture"),
        },
        content_type=MULTIPART_CONTENT,
    )
    assert response.status_code == 400 and MediaAsset.objects.count() == 0


def test_test_link_delete_removes_its_photos(logged_in):
    quiz = photo_quiz()
    authoring.publish(quiz, admin_id=ADMIN_ID)
    link = run_links.create(quiz, authoring.latest_published(quiz), expires_at=None, admin_id="a")
    player = Player(link.run)
    player.submit({f"{player.question('image_answer')}:image": upload()})
    assert MediaAsset.objects.count() == 1
    response = logged_in.post(f"/admin/tests/{link.id}/attempts/delete")
    assert response.status_code == 302 and MediaAsset.objects.count() == 0


def test_public_level_warns_before_upload():
    player = Player(run_of(photo_quiz(level="public")))
    assert 'role="note"' in player.html
    other = Player(run_of(photo_quiz(slug="other")))
    assert 'role="note"' not in other.html


def test_after_each_requirement_is_real(logged_in):
    quiz = photo_quiz()
    settings.set_override(settings.REVEAL_MOMENT, quiz, "after_each", admin_id=ADMIN_ID)
    edit = text(logged_in.get(f"/admin/quizzes/{quiz.id}/edit"))
    assert f"/admin/quizzes/{quiz.id}/requirements/use" in edit
    with pytest.raises(authoring.PublicationError):
        authoring.publish(quiz, admin_id=ADMIN_ID)
    logged_in.post(f"/admin/quizzes/{quiz.id}/requirements/use", {"key": settings.REVEAL_MOMENT})
    assert authoring.publish(quiz, admin_id=ADMIN_ID)


def test_reveal_at_end_says_waiting():
    quiz = photo_quiz()
    settings.set_override(settings.REVEAL_MOMENT, quiz, "at_end", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_LEVEL, quiz, "answers", admin_id=ADMIN_ID)
    player = Player(run_of(quiz))
    html = text(player.submit({f"{player.question('image_answer')}:image": upload()}))
    assert "Čeká na hodnocení: zatím 2 z 10 bodů" in html


def test_a_repeat_reveals_the_stored_photo_state():
    quiz = photo_quiz()
    settings.set_override(settings.REVEAL_MOMENT, quiz, "at_end", admin_id=ADMIN_ID)
    settings.set_override(settings.REVEAL_LEVEL, quiz, "answers", admin_id=ADMIN_ID)
    player = Player(run_of(quiz))
    question = player.question("image_answer")
    player.submit({f"{question}:image": upload()})
    html = text(player.submit({f"{question}:image": upload()}))
    assert "Čeká na hodnocení: zatím 2 z 10 bodů" in html and MediaAsset.objects.count() == 1


def test_bank_editor_asks_percent_and_quiz_editor_points(logged_in):
    quiz = make_quiz()
    bank = make_bank()
    in_quiz = text(logged_in.get(f"/admin/quizzes/{quiz.id}/questions/new?type=image_answer"))
    in_bank = text(logged_in.get(f"/admin/banks/{bank.id}/questions/new?type=image_answer"))
    assert 'class="editor editor-quiz' in in_quiz and 'class="editor editor-bank' in in_bank
    assert 'name="auto_points"' in in_quiz and 'name="auto_percent"' in in_bank


def test_row_of_five_at_twenty_percent_gives_one():
    """AC-55: a draw row sets the points, and the share follows."""
    quiz = make_quiz()
    bank = make_bank()
    add_bank_question(bank)
    from app.domain import banks

    banks.save_question(
        bank,
        None,
        "image_answer",
        photo_config(right=20, total=100),
        locales=("cs", "en", "uk"),
        tags=("foto",),
    )
    add_row(quiz, bank, count=1, points=5, tag="foto")
    player = Player(run_of(quiz))
    player.submit({f"{player.question('image_answer')}:image": upload()})
    row = AttemptAnswer.objects.get()
    assert row.auto_points == 1 and row.manual_max == 4
    player.attempt.refresh_from_db()
    assert player.attempt.score == 1 and player.attempt.max_score == 5


def test_files_stay_on_the_volume_and_are_named_by_the_server(media):
    player = Player(run_of(photo_quiz()))
    player.submit({f"{player.question('image_answer')}:image": upload(name="../../evil.php")})
    names = [path.name for path in Path(media).iterdir()]
    assert len(names) == 1 and names[0].endswith(".webp") and "evil" not in names[0]


def test_a_file_over_the_limit_is_refused_before_it_is_read(monkeypatch):
    def never(self, data, *, run_assets):
        raise AssertionError("read a file over the limit")

    monkeypatch.setattr(LocalMediaStorage, "store_participant_image", never)
    player = Player(run_of(photo_quiz()))
    big = upload(b"x" * (15 * 1024 * 1024 + 1))
    response = player.submit({f"{player.question('image_answer')}:image": big})
    assert response.status_code == 400 and "15 MB" in text(response)


def test_caddy_lets_several_photos_through_one_submission():
    caddyfile = (Path(__file__).parents[2] / "deploy" / "Caddyfile").read_text()
    assert "/a/*/submit" in caddyfile.split("@other")[0]


def test_a_body_over_the_proxy_limit_has_its_own_message():
    player = Player(run_of(photo_quiz()))
    page = player.client.get(f"/q/{player.attempt.run.quiz.slug}")
    assert "data-too-large=" in text(page)
