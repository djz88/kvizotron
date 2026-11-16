import re
from decimal import Decimal

import pytest
from django.db import IntegrityError

from app.api import admin_forms
from app.domain import authoring, settings
from app.domain.models import Attempt, Quiz
from tests.domain.helpers import ADMIN_ID, OPTION_A, OPTION_B, definition, make_bank, make_quiz

pytestmark = pytest.mark.django_db
QUESTION = {"prompt_cs": "Otázka", "option_0_cs": "A", "option_1_cs": "B", "correct_1": "on"}
HTMX = {"HX-Request": "true"}


def text(response):
    return response.content.decode()


def new_url(quiz):
    return f"/admin/quizzes/{quiz.id}/questions/new?type=choice"


def only_question(quiz):
    return authoring.editable_questions(quiz)[0]


def test_form_offers_points_scoring_and_sources(logged_in):
    html = text(logged_in.get(new_url(make_quiz()) + "&lang=en"))
    assert 'name="points"' in html and 'name="sources"' in html
    assert 'value="all_or_nothing"' in html and 'value="partial"' in html
    assert "Part by part" in html


def test_points_and_scoring_are_saved_and_change_the_maximum(logged_in):
    quiz = make_quiz()
    form = QUESTION | {"points": "7", "scoring": "partial"}
    assert logged_in.post(new_url(quiz), form).status_code == 302
    question = only_question(quiz)
    assert question["settings"]["points"] == 7
    assert question["scoring"] == "partial"
    assert authoring.publish(quiz, admin_id=ADMIN_ID).max_score == Decimal(7)


def test_editing_shows_and_keeps_saved_values(logged_in):
    quiz = make_quiz()
    form = QUESTION | {"points": "7", "scoring": "partial", "sources": "Kniha\nhttps://a.example"}
    logged_in.post(new_url(quiz), form)
    question_id = only_question(quiz)["id"]
    edit = f"/admin/quizzes/{quiz.id}/questions/{question_id}/edit"
    html = text(logged_in.get(edit))
    assert 'value="7"' in html
    assert re.search(r'value="partial"[^>]*selected', html)
    assert "Kniha\nhttps://a.example</textarea>" in html


@pytest.mark.parametrize("points", ["0", "101", "-1", "x", "1.5"])
def test_points_outside_1_to_100_are_refused(logged_in, points):
    quiz = make_quiz()
    response = logged_in.post(new_url(quiz), QUESTION | {"points": points})
    assert response.status_code == 200
    assert not quiz.revisions.exists()
    assert 'value="Otázka"' in text(response)


def test_scoring_not_offered_by_the_type_is_refused(logged_in):
    quiz = make_quiz()
    response = logged_in.post(new_url(quiz), QUESTION | {"scoring": "demo.exact"})
    assert response.status_code == 200
    assert not quiz.revisions.exists()


def test_more_than_ten_sources_are_refused(logged_in):
    quiz = make_quiz()
    lines = "\n".join(f"zdroj {n}" for n in range(11))
    response = logged_in.post(new_url(quiz), QUESTION | {"sources": lines})
    assert response.status_code == 200
    assert not quiz.revisions.exists()
    assert "zdroj 10</textarea>" in text(response)


def test_a_source_over_300_characters_is_refused(logged_in):
    quiz = make_quiz()
    assert logged_in.post(new_url(quiz), QUESTION | {"sources": "x" * 301}).status_code == 200
    assert not quiz.revisions.exists()


def test_blank_source_lines_are_dropped(logged_in):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), QUESTION | {"sources": " Kniha \n\n  \nDruhá"})
    assert only_question(quiz)["sources"] == ["Kniha", "Druhá"]


def test_second_post_with_the_same_form_key_adds_nothing(logged_in):
    quiz = make_quiz()
    html = text(logged_in.get(new_url(quiz)))
    key = re.search(r'name="form_key" value="([^"]+)"', html).group(1)
    form = QUESTION | {"form_key": key}
    assert logged_in.post(new_url(quiz), form).status_code == 302
    assert logged_in.post(new_url(quiz), form).status_code == 302
    assert len(authoring.editable_questions(quiz)) == 1


def test_going_back_and_saving_changes_under_the_same_key_keeps_the_changes(logged_in):
    quiz = make_quiz()
    form = QUESTION | {"form_key": "abc"}
    logged_in.post(new_url(quiz), form)
    logged_in.post(new_url(quiz), form | {"prompt_cs": "Opravená otázka", "points": "4"})
    questions = authoring.editable_questions(quiz)
    assert len(questions) == 1
    assert questions[0]["definition"]["prompt"]["cs"] == "Opravená otázka"
    assert questions[0]["settings"]["points"] == 4


def test_each_form_gets_its_own_key(logged_in):
    quiz = make_quiz()
    keys = {
        re.search(r'name="form_key" value="([^"]+)"', text(logged_in.get(new_url(quiz)))).group(1)
        for _ in range(2)
    }
    assert len(keys) == 2


def test_failed_form_keeps_its_key_so_the_retry_saves_once(logged_in):
    quiz = make_quiz()
    response = logged_in.post(new_url(quiz), QUESTION | {"form_key": "abc", "points": "0"})
    assert 'name="form_key" value="abc"' in text(response)
    form = QUESTION | {"form_key": "abc"}
    logged_in.post(new_url(quiz), form)
    logged_in.post(new_url(quiz), form)
    assert len(authoring.editable_questions(quiz)) == 1


def test_the_same_key_in_another_quiz_is_a_new_question(logged_in):
    first, second = make_quiz("prvni"), make_quiz("druhy")
    form = QUESTION | {"form_key": "abc"}
    logged_in.post(new_url(first), form)
    logged_in.post(new_url(second), form)
    assert len(authoring.editable_questions(second)) == 1


def test_race_on_slug_shows_the_form_error(logged_in, monkeypatch):
    def lost_the_race(self, quiz):
        raise IntegrityError("UNIQUE constraint failed: quiz.slug")

    monkeypatch.setattr(admin_forms.QuizForm, "apply_to", lost_the_race)
    response = logged_in.post(
        "/admin/quizzes/new",
        {
            "slug": "kviz",
            "supported_locales": ["cs"],
            "default_locale": "cs",
            "title_cs": "Název",
            "description_cs": "Popis",
        },
    )
    assert response.status_code == 200
    assert "identifik" in text(response)
    assert not Quiz.objects.exists()


def test_race_on_slug_in_settings_shows_the_form_error(logged_in, monkeypatch):
    def lost_the_race(self, quiz):
        raise IntegrityError("UNIQUE constraint failed: quiz.slug")

    quiz = make_quiz()
    monkeypatch.setattr(admin_forms.QuizBehaviourForm, "apply_to", lost_the_race)
    url = f"/admin/quizzes/{quiz.id}/settings"
    response = logged_in.post(url, {"slug": "jiny"})
    assert response.status_code == 200
    assert "identifik" in text(response)


def test_forms_warn_about_unsaved_changes(logged_in):
    quiz = make_quiz()
    assert "watch-changes" in text(logged_in.get(new_url(quiz)))
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/settings"))
    assert html.count("watch-changes") == 2


def test_editor_script_is_served_on_every_page(client):
    html = text(client.get("/"))
    assert "/assets/editor.js" in html
    assert client.get("/assets/editor.js").status_code == 200


def played(client, quiz, *, lang="cs"):
    """Publish, open a run and submit the correct answer to every question."""
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(client.post(f"/r/{run.id}/start", {"lang": lang}, headers=HTMX))
    fields = {
        name: re.search(rf'name="{name}" value="([^"]*)"', html).group(1)
        for name in ("attempt_token", "submission_key", "lang")
    }
    for question in run.current_revision.snapshot_json["questions"]:
        fields[f"{question['id']}:options[]"] = question["definition"]["correct"]
    action = re.search(r'action="(/a/[^"?]+/submit)(?:\?[^"]*)?"', html).group(1)
    return text(client.post(action, fields, headers=HTMX))


def quiz_with_sources(sources, locales=("cs",)):
    quiz = make_quiz(locales=locales)
    authoring.save_question(quiz, None, "choice", definition(locales), sources=sources)
    return quiz


def test_result_lists_sources_with_question_text_when_on(client):
    html = played(client, quiz_with_sources(["Učebnice, s. 112"]))
    assert "Učebnice, s. 112" in html and "Otázka cs" in html


def test_result_uses_the_language_of_the_attempt(client):
    html = played(client, quiz_with_sources(["Kniha"], ("cs", "uk")), lang="uk")
    assert "Otázka uk" in html and "Otázka cs" not in html


def test_result_hides_sources_when_off(client):
    quiz = quiz_with_sources(["Učebnice, s. 112"])
    settings.set_override(settings.SHOW_SOURCES, quiz, settings.ShowSources.OFF, admin_id=ADMIN_ID)
    html = played(client, quiz)
    assert "Učebnice" not in html
    assert Attempt.objects.get().status == Attempt.Status.SUBMITTED


def test_global_setting_hides_sources(client):
    settings.set_global(settings.SHOW_SOURCES, settings.ShowSources.OFF, admin_id=ADMIN_ID)
    assert "Učebnice" not in played(client, quiz_with_sources(["Učebnice"]))


def test_question_without_sources_is_not_listed(client):
    quiz = make_quiz()
    authoring.save_question(quiz, None, "choice", definition(("cs",), prompt="Bez"))
    authoring.save_question(quiz, None, "choice", definition(("cs",), prompt="Se"), sources=["K"])
    html = played(client, quiz)
    assert "Se cs" in html and "Bez cs" not in html


def test_only_https_line_becomes_a_link(client):
    html = played(
        client,
        quiz_with_sources(
            [
                "https://zakony.example/1993-3",
                "http://stare.example",
                "javascript:alert(1)",
                "https://a.example s mezerou",
            ]
        ),
    )
    assert '<a href="https://zakony.example/1993-3" rel="noopener noreferrer"' in html
    assert 'href="http://stare.example"' not in html and "http://stare.example" in html
    assert 'href="javascript' not in html
    assert 'href="https://a.example s' not in html


def test_markup_in_a_source_is_escaped(client):
    html = played(client, quiz_with_sources(['"><script>x', 'https://a.example/"><script>y']))
    assert "<script>x" not in html and "<script>y" not in html
    assert "&lt;script&gt;x" in html or "&#34;&gt;&lt;script&gt;x" in html


def test_sources_change_shows_in_the_overview(logged_in):
    quiz = quiz_with_sources(["Stará kniha"])
    authoring.publish(quiz, admin_id=ADMIN_ID)
    question_id = only_question(quiz)["id"]
    config = only_question(quiz)["definition"]
    authoring.save_question(quiz, question_id, "choice", config, sources=["Nová kniha"])
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/publish"))
    assert "Stará kniha" in html and "Nová kniha" in html


def test_published_revision_keeps_its_sources():
    quiz = quiz_with_sources(["Stará"])
    published = authoring.publish(quiz, admin_id=ADMIN_ID)
    question_id = only_question(quiz)["id"]
    config = only_question(quiz)["definition"]
    authoring.save_question(quiz, question_id, "choice", config, sources=["Nová"])
    assert published.snapshot_json["questions"][0]["sources"] == ["Stará"]


def test_change_of_points_does_not_empty_answers_when_switching():
    from app.domain import attempts

    quiz = make_quiz()
    question_id = authoring.save_question(quiz, None, "choice", definition(("cs",)), sources=["A"])
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    started = attempts.start(run)
    config = only_question(quiz)["definition"]
    authoring.save_question(
        quiz, question_id, "choice", config, points=5, scoring="partial", sources=["B"]
    )
    authoring.publish(quiz, admin_id=ADMIN_ID, decision="notify_switch")
    answers = {question_id: {"options": [OPTION_B]}}
    result = attempts.switch(started.attempt.id, started.token, answers)
    assert result.answers == answers and not result.changed


@pytest.mark.parametrize(
    ("correct", "cs", "en"),
    [
        ([OPTION_A], "100 %", "100 %"),
        ([OPTION_B], "0 %", "0 %"),
    ],
)
def test_whole_percentages_have_no_decimals(client, correct, cs, en):
    quiz = make_quiz()
    config = definition(("cs",))
    authoring.save_question(quiz, None, "choice", config)
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(client.post(f"/r/{run.id}/start", {"lang": "cs"}, headers=HTMX))
    fields = {
        name: re.search(rf'name="{name}" value="([^"]*)"', html).group(1)
        for name in ("attempt_token", "submission_key", "lang")
    }
    question = run.current_revision.snapshot_json["questions"][0]["id"]
    fields[f"{question}:options[]"] = correct
    action = re.search(r'action="(/a/[^"?]+/submit)(?:\?[^"]*)?"', html).group(1)
    assert cs in text(client.post(action, fields, headers=HTMX))


def test_percentage_is_written_for_the_language():
    from django.utils import translation

    from app.api.jinja import number

    with translation.override("cs"):
        assert number(50.0) == "50"
        assert number(12.5) == "12,5"
        assert number(Decimal("0.3333")) == "0,3333"
        assert number(Decimal("100.0000")) == "100"
    with translation.override("en"):
        assert number(12.5) == "12.5"
        assert number(50.0) == "50"
    with translation.override("uk"):
        assert number(12.5) == "12,5"


def test_a_result_with_decimals_uses_the_comma_in_czech(client):
    quiz = make_quiz()
    config = definition(("cs",))
    config["options"].append({"id": "cccc3333", "text": {"cs": "Třetí"}})
    config["correct"] = [OPTION_A, OPTION_B]
    config["allow_multiple"] = True
    authoring.save_question(quiz, None, "choice", config, points=1, scoring="partial")
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(client.post(f"/r/{run.id}/start", {"lang": "cs"}, headers=HTMX))
    fields = {
        name: re.search(rf'name="{name}" value="([^"]*)"', html).group(1)
        for name in ("attempt_token", "submission_key", "lang")
    }
    question = run.current_revision.snapshot_json["questions"][0]["id"]
    fields[f"{question}:options[]"] = [OPTION_A]
    action = re.search(r'action="(/a/[^"?]+/submit)(?:\?[^"]*)?"', html).group(1)
    page = text(client.post(action, fields, headers=HTMX))
    assert "0,5 / 1" in page and "50 %" in page


def test_explanation_is_saved_per_language(logged_in):
    quiz = make_quiz(locales=("cs", "uk"))
    form = QUESTION | {"prompt_uk": "П", "option_0_uk": "А", "option_1_uk": "Б"}
    form |= {"explanation_cs": " Protože \n tak ", "explanation_uk": "Тому"}
    assert logged_in.post(new_url(quiz), form).status_code == 302
    assert only_question(quiz)["explanation"] == {"cs": "Protože \n tak", "uk": "Тому"}


def test_blank_explanation_stores_nothing(logged_in):
    quiz = make_quiz()
    assert logged_in.post(new_url(quiz), QUESTION | {"explanation_cs": "  "}).status_code == 302
    assert only_question(quiz)["explanation"] == {}


def test_explanation_is_kept_when_the_form_is_refused(logged_in):
    quiz = make_quiz()
    form = QUESTION | {"explanation_cs": "Moje vysvětlení", "points": "1000"}
    response = logged_in.post(new_url(quiz), form)
    assert response.status_code == 200
    assert "Moje vysvětlení" in text(response)


def test_explanation_longer_than_the_limit_is_refused(logged_in):
    quiz = make_quiz()
    response = logged_in.post(new_url(quiz), QUESTION | {"explanation_cs": "x" * 2001})
    assert response.status_code == 200
    assert not authoring.editable_questions(quiz)


def test_editor_shows_the_stored_explanation(logged_in):
    quiz = make_quiz()
    authoring.save_question(
        quiz, None, "choice", definition(("cs",)), explanation={"cs": "Uložené vysvětlení"}
    )
    question_id = only_question(quiz)["id"]
    html = text(logged_in.get(f"/admin/quizzes/{quiz.id}/questions/{question_id}/edit"))
    assert "Uložené vysvětlení" in html


def test_participant_page_has_no_explanation(client):
    quiz = make_quiz()
    authoring.save_question(
        quiz, None, "choice", definition(("cs",)), explanation={"cs": "Tajné vysvětlení"}
    )
    authoring.publish(quiz, admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert "Tajné vysvětlení" not in text(client.post(f"/r/{run.id}/start"))


def test_a_question_select_names_the_current_quiz_value(logged_in):
    quiz = make_quiz()
    settings.set_override(settings.SHOW_SOURCES, quiz, "off", admin_id=ADMIN_ID)
    html = text(logged_in.get(new_url(quiz) + "&lang=en"))
    assert 'name="setting_show_sources"' in html
    assert "Use quiz setting (now: Hide)" in html


def test_a_stored_question_value_is_selected_when_editing(logged_in):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), QUESTION | {"setting_show_sources": "off"})
    url = f"/admin/quizzes/{quiz.id}/questions/{only_question(quiz)['id']}/edit"
    html = text(logged_in.get(url))
    assert re.search(r'<option value="off" selected', html)


def test_an_unknown_value_in_a_question_select_is_refused(logged_in):
    quiz = make_quiz()
    response = logged_in.post(new_url(quiz), QUESTION | {"setting_show_sources": "forged"})
    assert response.status_code == 200
    assert authoring.editable_questions(quiz) == []


def test_following_the_quiz_stores_no_value(logged_in):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), QUESTION | {"setting_show_sources": ""})
    assert only_question(quiz)["settings"] == {"points": 1}


def test_choosing_a_value_stores_it_and_following_again_removes_it(logged_in):
    quiz = make_quiz()
    logged_in.post(new_url(quiz), QUESTION | {"setting_show_sources": "off"})
    question = only_question(quiz)
    assert question["settings"]["show_sources"] == "off"
    url = f"/admin/quizzes/{quiz.id}/questions/{question['id']}/edit"
    logged_in.post(url, QUESTION | {"setting_show_sources": ""})
    assert "show_sources" not in only_question(quiz)["settings"]


def test_settings_for_another_type_are_not_offered(logged_in):
    html = text(logged_in.get(f"/admin/quizzes/{make_quiz().id}/questions/new?type=matching"))
    assert 'name="setting_none_option"' not in html
    assert 'name="setting_shuffle_options"' not in html
    assert 'name="setting_show_sources"' in html


def test_a_bank_question_has_the_question_level_too(logged_in):
    bank = make_bank()
    html = text(logged_in.get(f"/admin/banks/{bank.id}/questions/new?type=choice&lang=en"))
    assert "Use global setting (now: Show)" in html
    response = logged_in.post(
        f"/admin/banks/{bank.id}/questions/new?type=choice",
        QUESTION | {"setting_show_sources": "off"},
    )
    assert response.status_code == 302
    assert bank.questions.get().question_json["settings"]["show_sources"] == "off"
