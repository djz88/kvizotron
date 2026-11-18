"""Choosing a quiz type on the new-quiz and settings pages, deviations, the overview.

AC-171, ADR-0062.
"""

import re
from decimal import Decimal
from typing import cast

import pytest
from django.utils import translation

from app.contracts import REWARD_SOURCE, SCOREBOARD_VISIBILITY, QuizTypePlugin
from app.domain import authoring, quiz_types, rewards, run_flow, settings
from app.domain.models import AppSetting, Quiz
from app.kernel import registry
from app.kernel.models import PluginInstallation
from tests.domain.helpers import ADMIN_ID, make_quiz, published_quiz
from tests.support.photos import add_photo

pytestmark = pytest.mark.django_db
TYPES = ["practice", "final_test", "resit_exam", "mock_test", "contest", "pub_quiz", "basic"]
NEW = {"slug": "kviz", "supported_locales": ["cs"], "default_locale": "cs", "title_cs": "Název"}


@pytest.fixture
def english(logged_in):
    logged_in.get("/admin/?lang=en")  # the session keeps the language
    return logged_in


def table(type_id):
    return dict(cast(QuizTypePlugin, registry.get("quiz_type", type_id)).values())


def overrides(quiz):
    return dict(AppSetting.objects.filter(quiz=quiz).values_list("key", "value_json"))


def disable(module_id):
    PluginInstallation.objects.update_or_create(
        pk=module_id, defaults={"version": "1.0.0", "manifest_json": {}, "enabled": False}
    )


def text(response):
    return response.content.decode()


def type_url(quiz, type_id=None):
    url = f"/admin/quizzes/{quiz.id}/type"
    return f"{url}?type={type_id}" if type_id else url


def settings_url(quiz):
    return f"/admin/quizzes/{quiz.id}/settings"


def section(html, element_id):
    """The text of the element with this id, up to its closing tag."""
    found = re.search(rf'<(\w+)[^>]*id="{element_id}"[^>]*>(.*?)</\1>', html, re.S)
    return found.group(2) if found else ""


def marks(html):
    return set(re.findall(r'class="type-mark" id="mark-(\w+)"', html))


def label(key):
    with translation.override("en"):
        return str(settings.CATALOGUE[key].label)


def no_inline_code(html):
    assert ' style="' not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    unique_ids(html)


def unique_ids(html):
    """`section` finds the first element with an id, so an id the layout also uses would hide it."""
    ids = re.findall(r'(?<![\w-])id="([^"]+)"', html)
    assert len(ids) == len(set(ids)), sorted({found for found in ids if ids.count(found) > 1})


# The new-quiz form


def test_new_quiz_form_has_an_open_list_of_types_with_no_type_checked(english):
    html = text(english.get("/admin/quizzes/new"))
    choice = re.search(r'<details class="quiz-type-choice"([^>]*)>(.*?)</details>', html, re.S)
    assert choice is not None
    assert "open" in choice.group(1)
    assert "<summary>Quiz type</summary>" in choice.group(2)
    assert "<legend" not in choice.group(2)
    assert '<fieldset aria-label="Quiz type">' in choice.group(2)
    assert "Sets the quiz settings in one step" in choice.group(2)
    values = re.findall(r'<input type="radio" name="quiz_type" value="(\w*)"', choice.group(2))
    assert values == ["", *TYPES]
    assert re.search(r'name="quiz_type" value=""[^>]*checked', choice.group(2))
    assert "No type" in choice.group(2)
    assert "no time limit" in choice.group(2)  # Practice's description
    no_inline_code(html)


def test_every_field_of_the_new_quiz_form_has_its_own_wrapper(english):
    html = text(english.get("/admin/quizzes/new"))
    form = html[html.index('<form method="post">') : html.index("quiz-type-choice")]
    parts = re.split(r"(?=<div(?: class=\"[^\"]*\")?>\s*<(?:label|fieldset))", form)
    wrapped = [part for part in parts if re.match(r"<div", part)]
    featured = next(part for part in wrapped if 'name="featured"' in part)
    assert 'name="title_cs"' not in featured
    title = next(part for part in wrapped if 'name="title_cs"' in part)
    assert 'name="featured"' not in title
    assert 'name="slug"' in "".join(wrapped)


def test_a_new_quiz_takes_the_chosen_type(logged_in):
    assert logged_in.post("/admin/quizzes/new", NEW | {"quiz_type": "practice"}).status_code == 302
    quiz = Quiz.objects.get(slug="kviz")
    assert quiz.quiz_type == "practice"
    assert overrides(quiz) == table("practice")


def test_a_new_quiz_without_a_type_is_created_as_before(logged_in):
    assert logged_in.post("/admin/quizzes/new", NEW).status_code == 302
    quiz = Quiz.objects.get(slug="kviz")
    assert quiz.quiz_type == ""
    assert overrides(quiz) == {}


def test_an_unknown_type_on_the_new_quiz_is_a_form_error(logged_in):
    assert logged_in.post("/admin/quizzes/new", NEW | {"quiz_type": "gone"}).status_code == 200
    assert not Quiz.objects.exists()


def test_without_the_types_module_the_new_quiz_form_has_no_list(logged_in):
    disable("quiz_types.basic")
    html = text(logged_in.get("/admin/quizzes/new"))
    assert "quiz-type-choice" not in html and 'name="quiz_type"' not in html
    assert logged_in.post("/admin/quizzes/new", NEW | {"quiz_type": "practice"}).status_code == 302
    assert Quiz.objects.get(slug="kviz").quiz_type == ""


# The settings page


def test_settings_without_a_type_offers_to_choose_one(english):
    quiz = make_quiz()
    html = text(english.get(settings_url(quiz)))
    chooser = section(html, "quiz-type")
    assert f'<form method="get" action="{type_url(quiz)}"' in chooser
    assert re.findall(r'<option value="(\w+)"', chooser) == TYPES
    assert "Use type" in chooser
    assert "Remove type" not in chooser
    assert not marks(html)


def test_settings_bar_counts_deviations_and_marks_exactly_those_fields_in_basic_view(english):
    quiz = make_quiz()
    quiz_types.apply(quiz, "final_test", admin_id=ADMIN_ID)
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "45", admin_id=ADMIN_ID)
    # back to the global value, which is "on": a deviation without an override, an advanced field
    settings.set_override(settings.SHOW_SOURCES, quiz, None, admin_id=ADMIN_ID)
    html = text(english.get(settings_url(quiz)))  # the Basic view is the default
    bar = section(html, "quiz-type")
    assert "Final test" in bar and "Deviations: 2" in bar
    assert marks(html) == {settings.ATTEMPT_LIMIT, settings.SHOW_SOURCES}
    assert re.search(r'id="mark-attempt_limit">[^<]*type: 30 min', html)
    assert re.search(r'id="mark-show_sources">[^<]*type: Hide', html)
    no_inline_code(html)


def test_settings_bar_without_deviations_marks_nothing(english):
    quiz = make_quiz()
    quiz_types.apply(quiz, "final_test", admin_id=ADMIN_ID)
    html = text(english.get(settings_url(quiz)))
    assert "Deviations: 0" in section(html, "quiz-type")
    assert not marks(html)


def test_apply_again_and_change_type_lead_to_the_same_overview(english):
    quiz = make_quiz()
    quiz_types.apply(quiz, "final_test", admin_id=ADMIN_ID)
    bar = section(text(english.get(settings_url(quiz))), "quiz-type")
    assert f'href="{type_url(quiz, "final_test")}"' in bar
    assert "Apply again" in bar
    change = re.search(rf'<form method="get" action="{type_url(quiz)}".*?</form>', bar, re.S)
    assert change is not None and "Change type" in change.group(0)
    assert re.findall(r'<option value="(\w+)"', change.group(0)) == [
        type_id for type_id in TYPES if type_id != "final_test"
    ]
    assert f'action="/admin/quizzes/{quiz.id}/type/remove"' in bar


def test_a_type_of_a_disabled_module_shows_its_name_and_only_remove(english):
    quiz = make_quiz()
    quiz_types.apply(quiz, "final_test", admin_id=ADMIN_ID)
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "45", admin_id=ADMIN_ID)
    disable("quiz_types.basic")
    html = text(english.get(settings_url(quiz)))
    bar = section(html, "quiz-type")
    assert "Final test" in bar
    assert "Apply again" not in bar and "Change type" not in bar and "<select" not in bar
    assert f'action="/admin/quizzes/{quiz.id}/type/remove"' in bar
    assert not marks(html)


def test_a_type_no_longer_installed_shows_its_id_and_only_remove(english):
    quiz = make_quiz(quiz_type="gone")
    bar = section(text(english.get(settings_url(quiz))), "quiz-type")
    assert "gone" in bar and "Apply again" not in bar
    assert f'action="/admin/quizzes/{quiz.id}/type/remove"' in bar


# The overview


def test_overview_lists_changes_and_settings_back_to_the_global_value(english):
    quiz = make_quiz()
    quiz_types.apply(quiz, "contest", admin_id=ADMIN_ID)
    response = english.get(type_url(quiz, "practice"))
    assert response.status_code == 200
    html = text(response)
    changes = section(html, "changes")
    assert label(settings.NAVIGATION_MODE) in changes
    assert label(REWARD_SOURCE) in changes
    assert "global value (now: " in changes
    assert 'name="confirm" value="1"' in html
    assert 'name="type" value="practice"' in html
    no_inline_code(html)


def test_overview_names_adjusted_and_skipped_settings(english):
    settings.set_global(settings.ANSWERS_VISIBILITY, "public", admin_id=ADMIN_ID)
    disable("rewards.threshold")
    quiz = make_quiz()
    adjusted = section(text(english.get(type_url(quiz, "practice"))), "adjusted")
    assert label(settings.ANSWERS_VISIBILITY) in adjusted
    skipped = section(text(english.get(type_url(quiz, "contest"))), "skipped")
    assert label(REWARD_SOURCE) in skipped and "module is off" in skipped


def test_overview_warns_about_the_content_and_offers_the_run(english):
    """AC-185: the content warning stays; the run part is the choice."""
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    add_photo(quiz)
    html = text(english.get(type_url(quiz, "practice")))
    assert 'id="live-run"' not in html
    assert 'name="flow_choice" value="run"' in html
    assert label(settings.REVEAL_MOMENT) in section(html, "content-warning")
    assert 'name="confirm" value="1"' in html  # a warning does not refuse
    unique_ids(html)


def test_overview_with_nothing_to_change_says_so(english):
    quiz = make_quiz()
    quiz_types.apply(quiz, "final_test", admin_id=ADMIN_ID)
    html = text(english.get(type_url(quiz, "final_test")))
    assert "Nothing changes" in html
    assert 'name="confirm" value="1"' in html  # Apply again still remembers the type


def test_post_without_confirm_shows_the_overview_and_changes_nothing(english):
    quiz = make_quiz()
    response = english.post(type_url(quiz), {"type": "final_test"})
    assert response.status_code == 200
    assert 'id="changes"' in text(response)
    quiz.refresh_from_db()
    assert quiz.quiz_type == "" and overrides(quiz) == {}


def test_confirmed_post_applies_the_type(logged_in):
    quiz = make_quiz()
    response = logged_in.post(type_url(quiz), {"type": "final_test", "confirm": "1"})
    assert response.status_code == 302 and response.url == settings_url(quiz)
    quiz.refresh_from_db()
    assert quiz.quiz_type == "final_test"
    assert overrides(quiz) == table("final_test")


def test_an_open_run_does_not_refuse_the_type_and_keeps_its_values(english):
    """AC-171: a planned or open run keeps its values; the type applies to the quiz only."""
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"})
    kept = run_flow.of(run)
    shown = text(english.get(type_url(quiz, "practice")))
    assert 'name="confirm"' in shown
    assert 'value="run"' not in shown  # the run cannot take it: only "next" is offered
    assert "Answers after each question cannot go with a visible scoreboard." in section(
        shown, "refused"
    )
    response = english.post(
        type_url(quiz), {"type": "practice", "confirm": "1", "flow_choice": "next"}
    )
    assert response.status_code == 302
    quiz.refresh_from_db()
    assert quiz.quiz_type == "practice"
    run.refresh_from_db()
    assert run_flow.of(run) == kept


def test_an_unknown_or_disabled_type_is_not_found(logged_in):
    quiz = make_quiz()
    assert logged_in.get(type_url(quiz, "gone")).status_code == 404
    assert logged_in.get(type_url(quiz)).status_code == 404
    assert logged_in.post(type_url(quiz), {"type": "gone", "confirm": "1"}).status_code == 404
    disable("quiz_types.basic")
    assert logged_in.get(type_url(quiz, "practice")).status_code == 404
    assert logged_in.post(type_url(quiz), {"type": "practice", "confirm": "1"}).status_code == 404
    quiz.refresh_from_db()
    assert quiz.quiz_type == ""


def test_remove_forgets_the_type_and_keeps_the_values(logged_in):
    quiz = make_quiz()
    quiz_types.apply(quiz, "final_test", admin_id=ADMIN_ID)
    response = logged_in.post(f"/admin/quizzes/{quiz.id}/type/remove")
    assert response.status_code == 302 and response.url == settings_url(quiz)
    quiz.refresh_from_db()
    assert quiz.quiz_type == ""
    assert overrides(quiz) == table("final_test")
    assert logged_in.get(f"/admin/quizzes/{quiz.id}/type/remove").status_code == 405


def test_an_archived_quiz_refuses_every_type_action(logged_in):
    quiz = published_quiz()
    quiz_types.apply(quiz, "final_test", admin_id=ADMIN_ID)
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    assert logged_in.get(type_url(quiz, "practice")).status_code == 409
    posted = logged_in.post(type_url(quiz), {"type": "practice", "confirm": "1"})
    assert posted.status_code == 409
    assert logged_in.post(f"/admin/quizzes/{quiz.id}/type/remove").status_code == 409
    quiz.refresh_from_db()
    assert quiz.quiz_type == "final_test"
    assert overrides(quiz) == table("final_test")
    assert 'id="quiz-type"' not in text(logged_in.get(settings_url(quiz)))


def test_type_pages_require_login(client):
    quiz = make_quiz()
    assert client.get(type_url(quiz, "practice")).status_code == 302
    client.post(type_url(quiz), {"type": "practice", "confirm": "1"})
    quiz.refresh_from_db()
    assert quiz.quiz_type == ""
    Quiz.objects.filter(pk=quiz.pk).update(quiz_type="pub_quiz")
    removed = client.post(f"/admin/quizzes/{quiz.id}/type/remove")
    assert removed.status_code == 302 and "/login" in removed["Location"]
    quiz.refresh_from_db()
    assert quiz.quiz_type == "pub_quiz"


def test_unique_ids_ignores_data_id_attributes():
    unique_ids('<p data-id="x" id="x"></p>')
    with pytest.raises(AssertionError):
        unique_ids('<p id="x"></p><p id="x"></p>')


def test_mark_is_described_by_its_control(english):
    quiz = make_quiz()
    quiz_types.apply(quiz, "final_test", admin_id=ADMIN_ID)
    settings.set_override(settings.ATTEMPT_LIMIT, quiz, "45", admin_id=ADMIN_ID)
    html = text(english.get(settings_url(quiz)))
    control = re.search(r"<[^>]*\bname=\"attempt_limit\"[^>]*>", html)
    assert control is not None
    assert 'aria-describedby="mark-attempt_limit' in control.group(0)


def test_new_quiz_with_a_type_gone_meanwhile_says_so(logged_in, monkeypatch):
    def gone(*args, **kwargs):
        raise quiz_types.UnknownType("practice")

    monkeypatch.setattr(quiz_types, "apply", gone)
    logged_in.get("/admin/?lang=en")
    response = logged_in.post("/admin/quizzes/new", NEW | {"quiz_type": "practice"}, follow=True)
    shown = r'<p class="notice" role="(\w+)">[^<]*is no longer available'
    notice = re.search(shown, text(response))
    assert notice is not None and notice.group(1) == "status"  # information, not an error
    assert Quiz.objects.get(slug="kviz").quiz_type == ""


def live_quiz():
    quiz = published_quiz()
    return quiz, authoring.open_run(quiz, admin_id=ADMIN_ID)


def test_type_overview_offers_the_run(english):
    """AC-185: a live run gets the radios on the overview, inside the confirm form."""
    quiz, run = live_quiz()
    html = text(english.get(type_url(quiz, "practice")))
    assert f"Apply the change to run {run.run_no} too?" in html
    assert 'name="flow_choice" value="next"' in html
    assert 'id="live-run"' not in html
    assert html.index('name="flow_choice"') > html.index('name="confirm"')


def test_type_apply_with_run_applies_to_the_run(english):
    """AC-185: "run" writes the type's values to the run."""
    quiz, run = live_quiz()
    response = english.post(
        type_url(quiz), {"type": "practice", "confirm": "1", "flow_choice": "run"}
    )
    assert response.status_code == 302
    run.refresh_from_db()
    assert run_flow.of(run)[settings.NAVIGATION_MODE] == "step_no_back"
    assert run_flow.of(run)[settings.REVEAL_MOMENT] == "after_each"


def test_type_apply_without_an_answer_writes_nothing(english):
    """AC-185: no answer is a 400 and the quiz is untouched."""
    quiz, run = live_quiz()
    before = dict(run.flow_json)
    response = english.post(type_url(quiz), {"type": "practice", "confirm": "1"})
    assert response.status_code == 400
    html = text(response)
    assert f"Apply the change to run {run.run_no} too?" in html
    assert "Use the type" in html and "Apply the type" not in html
    quiz.refresh_from_db()
    run.refresh_from_db()
    assert quiz.quiz_type == "" and overrides(quiz) == {}
    assert run.flow_json == before


def test_type_refused_for_the_run_is_409_and_saves_nothing(english):
    """AC-185: a run that cannot take the change gets the reason and nothing is written."""
    quiz = published_quiz()
    texts = {"cs": {"name": "Cena", "description": "", "claim": ""}}
    rule = rewards.RuleData(
        kind="threshold", texts=texts, threshold_unit="percent", threshold_value=Decimal(50)
    )
    rewards.save_rule(quiz, rule, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    before_overrides = overrides(quiz)
    before = dict(run.flow_json)
    response = english.post(
        type_url(quiz), {"type": "practice", "confirm": "1", "flow_choice": "run"}
    )
    html = text(response)
    assert response.status_code == 409
    assert f"Run {run.run_no} cannot take this change:" in html
    assert "Use the type" in html
    assert 'name="type" value="practice"' in html and 'name="confirm" value="1"' in html
    quiz.refresh_from_db()
    run.refresh_from_db()
    assert quiz.quiz_type == "" and overrides(quiz) == before_overrides
    assert run.flow_json == before


def test_type_next_keeps_the_run(english):
    """AC-185: "next" applies the type to the quiz only."""
    quiz, run = live_quiz()
    before = dict(run.flow_json)
    response = english.post(
        type_url(quiz), {"type": "practice", "confirm": "1", "flow_choice": "next"}
    )
    assert response.status_code == 302
    run.refresh_from_db()
    assert run.flow_json == before
    quiz.refresh_from_db()
    assert quiz.quiz_type == "practice"


def test_type_without_a_change_for_the_run_asks_nothing(english):
    """AC-185: no live run, or values the run already has, ask nothing."""
    quiz = make_quiz()
    html = text(english.get(type_url(quiz, "practice")))
    assert 'name="flow_choice"' not in html
    quiz.delete()
    quiz, run = live_quiz()
    run.flow_json = (
        run_flow.of(run)
        | table("practice")
        | {key: run_flow.of(run)[key] for key in run_flow.KEYS if key not in table("practice")}
    )
    run.save(update_fields=["flow_json"])
    html = text(english.get(type_url(quiz, "practice")))
    assert 'name="flow_choice"' not in html
    response = english.post(type_url(quiz), {"type": "practice", "confirm": "1"})
    assert response.status_code == 302


def test_type_remove_asks_nothing(english):
    """AC-185: forgetting the type writes no value."""
    quiz, run = live_quiz()
    quiz_types.apply(quiz, "practice", admin_id=ADMIN_ID, flow_choice="next")
    before = dict(run.flow_json)
    response = english.post(f"/admin/quizzes/{quiz.id}/type/remove")
    assert response.status_code == 302
    run.refresh_from_db()
    assert run.flow_json == before


def test_global_page_says_runs_keep_their_values(english):
    """AC-185: one sentence under the heading."""
    html = text(english.get("/admin/settings?lang=en"))
    assert 'id="runs-keep"' in html
    assert "planned and open runs keep their values" in section(html, "runs-keep")
