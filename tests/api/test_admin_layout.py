"""Where things are in the administration (FR-51): one place for each kind of setting."""

import re
from pathlib import Path

import pytest

from app.contracts import COLOR_PALETTE
from app.domain import authoring, settings
from app.domain.models import AppSetting, QuizRevision, QuizRun
from tests.domain.helpers import ADMIN_ID, add_question, make_quiz, published_quiz

pytestmark = pytest.mark.django_db
APP = Path(__file__).resolve().parents[2] / "app"
TABS = ("edit", "runs", "revisions", "settings")


def base(quiz):
    return f"/admin/quizzes/{quiz.id}"


def text(response):
    return response.content.decode()


def current_tab(html):
    tabs = html.split('class="tabs"')[1].split("</nav>")[0]
    return re.findall(r'<a href="([^"]+)" aria-current="page">', tabs)


def behaviour(quiz, **fields):
    return {"slug": quiz.slug, **fields}


def content(quiz, **fields):
    return {
        "supported_locales": quiz.supported_locales,
        "default_locale": quiz.default_locale,
        "title_cs": "Název",
        "description_cs": "Popis",
        **fields,
    }


@pytest.mark.parametrize("tab", TABS)
def test_quiz_tabs_are_shared_and_mark_the_current_one(logged_in, tab):
    quiz = make_quiz()
    html = text(logged_in.get(f"{base(quiz)}/{tab}"))
    assert current_tab(html) == [f"{base(quiz)}/{tab}"]
    for other in TABS:
        assert f'href="{base(quiz)}/{other}"' in html


def test_run_page_belongs_to_the_runs_tab(logged_in):
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert current_tab(text(logged_in.get(f"/admin/runs/{run.id}"))) == [f"{base(quiz)}/runs"]


def test_questions_tab_holds_no_settings(logged_in):
    html = text(logged_in.get(f"{base(make_quiz())}/edit"))
    assert 'name="slug"' not in html
    assert 'name="revision_switch_policy"' not in html
    assert "/archive" not in html


def test_question_row_shows_type_points_and_missing_translation(logged_in):
    quiz = make_quiz(locales=("cs", "en"))
    config = {
        "prompt": {"cs": "Otázka"},
        "options": [
            {"id": "a", "text": {"cs": "Ano"}},
            {"id": "b", "text": {"cs": "Ne"}},
        ],
        "correct": ["a"],
    }
    authoring.save_question(quiz, None, "choice", config)
    html = text(logged_in.get(f"{base(quiz)}/edit?lang=en"))
    assert "Choice" in html
    assert "1 point" in html or "Points: 1" in html
    assert "To fix: en" in html


def test_add_question_menu_uses_readable_names(logged_in):
    html = text(logged_in.get(f"{base(make_quiz())}/edit?lang=en"))
    assert "type=choice" in html and ">Choice<" in html
    assert "preset=yes_no" in html
    assert ">Yes or no<" in html


def test_settings_tab_has_three_parts_and_says_when_changes_apply(showing_all):
    logged_in = showing_all
    quiz = make_quiz()
    html = text(logged_in.get(f"{base(quiz)}/settings?lang=en"))
    assert "after you publish" in html and "apply immediately" in html
    assert 'name="title_cs"' in html and 'name="description_cs"' in html
    assert 'name="slug"' in html and 'name="revision_switch_policy"' in html
    assert 'name="color_palette"' in html
    assert f"{base(quiz)}/archive" in html and f"{base(quiz)}/duplicate" in html


def test_saving_title_creates_a_draft_and_returns_to_settings(logged_in):
    quiz = published_quiz()
    response = logged_in.post(f"{base(quiz)}/edit", content(quiz, title_cs="Nový"))
    assert response["Location"] == f"{base(quiz)}/settings"
    assert quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_saving_address_and_behaviour_creates_no_draft(logged_in):
    quiz = published_quiz()
    response = logged_in.post(f"{base(quiz)}/settings", behaviour(quiz, featured="on"))
    assert response["Location"] == f"{base(quiz)}/settings"
    quiz.refresh_from_db()
    assert quiz.featured
    assert not quiz.revisions.filter(status=QuizRevision.Status.DRAFT).exists()


def test_address_can_change_before_first_publication(logged_in):
    quiz = make_quiz("stary")
    logged_in.post(f"{base(quiz)}/settings", {"slug": "novy"})
    quiz.refresh_from_db()
    assert quiz.slug == "novy"


def test_address_is_locked_after_first_publication(logged_in):
    quiz = published_quiz("stary")
    logged_in.post(f"{base(quiz)}/settings", {"slug": "novy"})
    quiz.refresh_from_db()
    assert quiz.slug == "stary"


def test_address_already_taken_is_refused(logged_in):
    make_quiz("obsazeno")
    quiz = make_quiz("volne")
    html = text(logged_in.post(f"{base(quiz)}/settings", {"slug": "obsazeno"}))
    assert "errorlist" in html
    quiz.refresh_from_db()
    assert quiz.slug == "volne"


def test_invalid_content_form_shows_the_settings_tab_with_the_error(logged_in):
    quiz = make_quiz()
    response = logged_in.post(f"{base(quiz)}/edit", {"default_locale": "cs"})
    html = text(response)
    assert response.status_code == 200
    assert current_tab(html) == [f"{base(quiz)}/settings"]
    assert "errorlist" in html


def test_description_longer_than_the_limit_is_refused(logged_in):
    quiz = make_quiz(description={})
    logged_in.post(f"{base(quiz)}/edit", content(quiz, description_cs="x" * 301))
    quiz.refresh_from_db()
    assert quiz.description == {}


def test_settings_tab_of_archived_quiz_has_no_forms_and_post_is_409(logged_in):
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    response = logged_in.get(f"{base(quiz)}/settings")
    html = text(response)
    assert response.status_code == 200
    assert 'name="slug"' not in html and 'name="title_cs"' not in html
    assert f"{base(quiz)}/restore" in html and f"{base(quiz)}/duplicate" in html
    assert logged_in.post(f"{base(quiz)}/settings", {"slug": "x"}).status_code == 409


def test_runs_tab_shows_running_panel_and_history(logged_in):
    quiz = published_quiz()
    authoring.close_run(authoring.open_run(quiz, admin_id=ADMIN_ID), admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"{base(quiz)}/runs"))
    assert 'class="panel"' in html and f"{base(quiz)}/qr.svg" in html
    assert f"/admin/runs/{run.id}" in html
    history = html.split("</table>")[0]  # the comparison of runs follows in its own table
    assert history.count("<tr>") == 3  # header and two runs


def test_runs_tab_without_a_running_run_has_no_panel(logged_in):
    html = text(logged_in.get(f"{base(published_quiz())}/runs"))
    assert 'class="panel"' not in html


def test_header_links_results_of_the_running_run_next_to_preview(logged_in):
    quiz = published_quiz()
    authoring.close_run(authoring.open_run(quiz, admin_id=ADMIN_ID), admin_id=ADMIN_ID)
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"{base(quiz)}/settings"))
    meta = html[html.index('class="quiz-meta"') : html.index('class="tabs"')]
    assert f"/admin/runs/{run.id}/statistics" in meta
    assert f"/admin/runs/{run.id}/scoreboard" in meta
    assert f"/q/{quiz.slug}/r/{run.id}/scoreboard?view=projector" in meta


def test_header_links_results_of_the_last_ended_run(logged_in):
    quiz = published_quiz()
    run = authoring.open_run(quiz, admin_id=ADMIN_ID)
    authoring.close_run(run, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"{base(quiz)}/edit"))
    meta = html[html.index('class="quiz-meta"') : html.index('class="tabs"')]
    assert f"/admin/runs/{run.id}/statistics" in meta


def test_header_without_runs_has_no_result_links(logged_in):
    html = text(logged_in.get(f"{base(published_quiz())}/edit"))
    assert '/statistics"' not in html


def test_runs_tab_links_statistics_and_scoreboard_of_each_run(logged_in):
    quiz = published_quiz()
    first = authoring.open_run(quiz, admin_id=ADMIN_ID)
    authoring.close_run(first, admin_id=ADMIN_ID)
    running = authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"{base(quiz)}/runs"))
    panel = html[html.index('class="panel"') : html.index("<table")]
    assert f"/admin/runs/{running.id}/statistics" in panel
    assert f"/admin/runs/{running.id}/scoreboard" in panel
    history, comparison = html[html.index("<table") :].split("</table>")[:2]
    assert '/statistics"' not in history  # the history table is already as wide as a page
    for run in (first, running):
        assert f"/admin/runs/{run.id}/statistics" in comparison
        assert f"/admin/runs/{run.id}/scoreboard" in comparison


def test_revisions_tab_lists_only_revisions(logged_in):
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get(f"{base(quiz)}/revisions"))
    assert f"{base(quiz)}/revisions/1/compare" in html
    assert "/admin/runs/" not in html.split('class="tabs"')[1]


def started():
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    return quiz


def finished():
    quiz = published_quiz()
    authoring.close_run(authoring.open_run(quiz, admin_id=ADMIN_ID), admin_id=ADMIN_ID)
    return quiz


def running_with_changes():
    quiz = started()
    add_question(quiz, prompt="Další")
    return quiz


def archived():
    quiz = published_quiz()
    authoring.archive_quiz(quiz, admin_id=ADMIN_ID)
    return quiz


@pytest.mark.parametrize(
    ("setup", "label", "status"),
    [
        (make_quiz, "Start the quiz", "The quiz is not running"),
        (finished, "Start again", "Run 1 has ended"),
        (running_with_changes, "Publish changes", "Run 1 is running"),
        (started, "End the run", "Run 1 is running"),
        (archived, "Restore from archive", "Archived"),
    ],
    ids=lambda value: getattr(value, "__name__", None) if callable(value) else None,
)
def test_header_follows_the_state(logged_in, setup, label, status):
    html = text(logged_in.get(f"{base(setup())}/edit?lang=en"))
    assert label in html
    assert status in html


def test_never_published_quiz_shows_one_tag(logged_in):
    html = text(logged_in.get(f"{base(make_quiz())}/edit?lang=en"))
    assert "Not published" in html
    assert "Unpublished changes" not in html


def test_published_quiz_with_changes_shows_both_tags(logged_in):
    quiz = published_quiz()
    add_question(quiz, prompt="Další")
    html = text(logged_in.get(f"{base(quiz)}/edit?lang=en"))
    assert "Published revision: 1" in html and "Unpublished changes" in html


def hash_of(html):
    return re.search(r'name="snapshot_hash" value="([^"]*)"', html).group(1)


def test_start_with_changes_shows_overview_then_publishes_and_opens(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    html = text(logged_in.get(f"{base(quiz)}/edit?lang=en"))
    assert f"{base(quiz)}/publish?start=1" in html
    page = text(logged_in.get(f"{base(quiz)}/publish?start=1&lang=en"))
    assert 'name="start" value="1"' in page and "Start the quiz" in page
    response = logged_in.post(
        f"{base(quiz)}/publish", {"snapshot_hash": hash_of(page), "start": "1"}
    )
    run = QuizRun.objects.get(quiz=quiz)
    assert response["Location"] == f"/admin/runs/{run.id}"
    assert run.current_revision.status == QuizRevision.Status.PUBLISHED


def test_start_without_changes_posts_to_runs(logged_in):
    quiz = published_quiz()
    html = text(logged_in.get(f"{base(quiz)}/edit"))
    assert f'action="{base(quiz)}/runs"' in html
    assert "publish?start=1" not in html


def test_start_on_a_quiz_never_published_leads_to_the_publication_page(logged_in):
    quiz = make_quiz()
    assert f"{base(quiz)}/publish?start=1" in text(logged_in.get(f"{base(quiz)}/edit"))
    html = text(logged_in.get(f"{base(quiz)}/publish?start=1&lang=en"))
    assert "The quiz has no questions." in html


def test_stale_start_shows_the_page_and_opens_nothing(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    response = logged_in.post(f"{base(quiz)}/publish", {"snapshot_hash": "old", "start": "1"})
    assert response.status_code == 200
    assert 'name="start" value="1"' in text(response)
    assert not quiz.runs.exists()
    assert authoring.latest_published(quiz) is None


def test_start_when_a_run_appeared_meanwhile_publishes_without_opening_another(logged_in):
    settings.set_global(settings.REVISION_SWITCH_POLICY, "let_finish", admin_id=None)
    quiz = started()
    add_question(quiz, prompt="Další")
    page = text(logged_in.get(f"{base(quiz)}/publish?start=1"))
    assert 'name="start"' not in page
    logged_in.post(f"{base(quiz)}/publish", {"snapshot_hash": hash_of(page), "start": "1"})
    assert quiz.runs.count() == 1
    assert authoring.latest_published(quiz).revision_no == 2


def test_publish_only_does_not_open_a_run(logged_in):
    quiz = make_quiz()
    add_question(quiz)
    page = text(logged_in.get(f"{base(quiz)}/publish"))
    assert 'name="start"' not in page
    logged_in.post(f"{base(quiz)}/publish", {"snapshot_hash": hash_of(page)})
    assert authoring.latest_published(quiz) is not None
    assert not quiz.runs.exists()


def test_end_run_asks_for_confirmation(logged_in):
    quiz = started()
    run = quiz.runs.get()
    assert f"/admin/runs/{run.id}/close" in text(logged_in.get(f"{base(quiz)}/edit"))
    page = logged_in.get(f"/admin/runs/{run.id}/close")
    assert page.status_code == 200 and f'action="/admin/runs/{run.id}/close"' in text(page)
    run.refresh_from_db()
    assert run.status == QuizRun.Status.OPEN
    assert logged_in.post(f"/admin/runs/{run.id}/close").status_code == 302
    run.refresh_from_db()
    assert run.status == QuizRun.Status.CLOSED


def test_main_navigation_marks_the_current_section(logged_in):
    html = text(logged_in.get("/admin/settings"))
    assert '<a href="/admin/settings" aria-current="page">' in html
    html = text(logged_in.get(f"{base(make_quiz())}/edit"))
    assert '<a href="/admin/quizzes" aria-current="page">' in html


def test_language_dropdown_shows_the_active_flag(logged_in):
    html = text(logged_in.get("/admin/quizzes?lang=en"))
    summary = html.split('class="dropdown language"')[1].split("</summary>")[0]
    assert "flag-en.svg" in summary and 'alt="English"' in summary
    assert "lang=cs" in html and "flag-cs.svg" in html


def test_administration_uses_the_global_palette(logged_in):
    settings.set_global(COLOR_PALETTE, "red_plum", admin_id=None)
    quiz = make_quiz()
    settings.set_override(COLOR_PALETTE, quiz, "indigo_pink", admin_id=None)
    assert 'data-palette="red_plum"' in text(logged_in.get(f"{base(quiz)}/edit"))


def test_global_settings_page_offers_the_palette(logged_in):
    html = text(logged_in.get("/admin/settings?lang=en"))
    assert 'name="color_palette"' in html and "Blue and teal" in html


def test_saving_palette_globally(logged_in):
    logged_in.post("/admin/settings", {"color_palette": "green_blue"})
    assert settings.resolve(COLOR_PALETTE) == "green_blue"


def test_quiz_list_shows_the_same_tags(logged_in):
    quiz = published_quiz()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    html = text(logged_in.get("/admin/quizzes?lang=en"))
    assert "Published revision: 1" in html and "Run 1 is running" in html


def test_no_template_carries_an_inline_style_or_script():
    # The one exception is the colours block of the layout, which the CSP allows by its nonce.
    found = [
        str(path)
        for path in APP.rglob("*.html")
        if re.search(
            r"\sstyle=|<style(?![^>]*\snonce=)|<script(?![^>]*\ssrc=)",
            path.read_text(encoding="utf-8"),
        )
    ]
    assert found == []


def test_settings_tab_survives_a_stored_palette_no_longer_offered(logged_in):
    quiz = make_quiz()
    AppSetting.objects.create(key=COLOR_PALETTE, quiz=None, value_json="retired")
    AppSetting.objects.create(key=COLOR_PALETTE, quiz=quiz, value_json="retired")
    response = logged_in.get(f"{base(quiz)}/settings")
    assert response.status_code == 200
    assert 'data-palette="blue_teal"' in text(response)


def test_quiz_form_refuses_pages_with_inherited_after_each(logged_in):
    """AC-88"""
    quiz = published_quiz()
    settings.set_global(settings.REVEAL_MOMENT, "after_each", admin_id=None)
    response = logged_in.post(f"{base(quiz)}/settings", behaviour(quiz, navigation_mode="pages"))
    assert response.status_code == 200
    assert settings.quiz_override(settings.NAVIGATION_MODE, quiz) is None


def test_tabs_are_four_and_more(logged_in):
    """AC-86: Questions, Runs, Grading, Settings, and More with test links and revisions."""
    quiz = make_quiz()
    html = text(logged_in.get(f"{base(quiz)}/edit"))
    nav = html.split('class="tabs"')[1].split("</nav>")[0]
    top, more = nav.split('class="tab-more')
    assert re.findall(r'<li><a href="[^"]+/(\w+)"', top) == ["edit", "runs", "grading", "settings"]
    assert f"{base(quiz)}/tests" in more and f"{base(quiz)}/revisions" in more


def test_more_is_marked_on_its_pages(logged_in):
    quiz = make_quiz()
    for tab in ("tests", "revisions"):
        nav = text(logged_in.get(f"{base(quiz)}/{tab}")).split('class="tabs"')[1]
        assert re.search(r'<summary aria-current="page"', nav)
    nav = text(logged_in.get(f"{base(quiz)}/edit")).split('class="tabs"')[1]
    assert not re.search(r'<summary aria-current="page"', nav)


def test_run_page_basic_hides_deeper_sections(logged_in):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    for tab in ("statistics", "scoreboard", "attempts"):
        assert f'id="{tab}"' in text(logged_in.get(f"/admin/runs/{run.id}/{tab}?lang=en"))
    html = text(logged_in.get(f"/admin/runs/{run.id}/settings?lang=en"))
    assert f"/admin/runs/{run.id}/period" not in html
    assert f"/admin/runs/{run.id}/code" not in html
    overview = text(logged_in.get(f"/admin/runs/{run.id}?lang=en"))
    assert f"/admin/runs/{run.id}/deadline" in overview  # the deadline is common work


RUN_TAB_SECTIONS = {
    "attempts": ("participants", "attempts"),
    "scoreboard": ("scoreboard",),
    "statistics": ("statistics",),
    "export": ("export",),
    "settings": ("access-code", "data"),
}


def test_run_tabs_have_their_main_section_and_every_jump_target(showing_all):
    """AC-184: each tab has its own section ids; each jump link lands on an id of its page."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    for tab, ids in RUN_TAB_SECTIONS.items():
        html = text(showing_all.get(f"/admin/runs/{run.id}/{tab}?lang=en"))
        for section in ids:
            assert f'id="{section}"' in html, (tab, section)
        panel = html[html.index('class="section-panel"') : html.index("</aside>")]
        for target in re.findall(r'<li><a href="#([^"]+)"', panel):
            assert f'id="{target}"' in html, (tab, target)


def test_run_page_basic_shows_a_set_code(logged_in):
    from app.domain import access_codes

    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    access_codes.set_code(run, "ABC123", admin_id=ADMIN_ID)
    html = text(logged_in.get(f"/admin/runs/{run.id}/settings?lang=en"))
    assert "An access code is set." in html
    assert f"/admin/runs/{run.id}/code" in html


def test_run_page_all_shows_everything(showing_all):
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    html = text(showing_all.get(f"/admin/runs/{run.id}/settings?lang=en"))
    assert f"/admin/runs/{run.id}/period" in html
    assert f"/admin/runs/{run.id}/code" in html


def test_more_tab_arrow_points_right_when_open():
    """The list opens to the right of "More", so the open arrow points there, not down."""
    css = (
        Path(__file__).resolve().parents[2] / "app/plugins/theme_default/assets/theme.css"
    ).read_text()
    rule = re.search(r"\.tab-more\[open\] > summary::after \{([^}]*)\}", css)
    assert rule and "rotate(-90deg)" in rule.group(1)


def test_more_tab_arrow_points_down_while_closed_and_stays_on_its_line():
    """Closed, "More" points down to say it opens; open, it points right at the list."""
    css = (
        Path(__file__).resolve().parents[2] / "app/plugins/theme_default/assets/theme.css"
    ).read_text()
    closed = re.search(r"\.tab-more:not\(\[open\]\) > summary::after \{([^}]*)\}", css)
    assert closed and "rotate(0" in closed.group(1)
    summary = re.search(r"\.tab-more > summary \{([^}]*)\}", css)
    assert summary and "white-space: nowrap" in summary.group(1)


def test_quiz_settings_put_copy_and_archive_first_and_every_section_as_wide(logged_in):
    """AC-168: copy and archive is a bar on top, not a section; the sections share one width."""
    quiz = make_quiz()
    html = text(logged_in.get(f"{base(quiz)}/settings?lang=en"))
    main = html[html.index('class="panel-main"') :]
    bar = re.search(r'<div class="actions quiz-copy" id="copy">.*?</div>', main, re.S)
    assert bar and "/duplicate" in bar.group(0) and "/archive" in main
    assert main.index('id="copy"') < main.index('id="title"')
    sections = re.findall(r'<section class="(form-section[^"]*)"', main)
    assert sections and all("settings-form" in classes for classes in sections), sections
    panel = html[html.index('class="section-panel"') : html.index("</aside>")]
    assert 'href="#copy"' not in panel
    assert (
        panel.index('href="#title"')
        < panel.index('href="#group-')
        < panel.index('href="#branding"')
    )
