"""AC-73, AC-74: name and e-mail asked on the pages, refused, and filled in later."""

import pytest

from app.domain import authoring, run_schedule
from app.domain.models import Attempt, Participant
from tests.domain.helpers import ADMIN_ID, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db


def text(response):
    return response.content.decode()


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def a_run(**rules):
    rules = {"ask_name": "required"} | rules
    return authoring.open_run(published_quiz(), admin_id=ADMIN_ID, rules=rules)


class Browser:
    def __init__(self, run):
        self.run = run
        self.client = FormClient()
        self.html = ""

    def start(self, **fields):
        response = self.client.post(f"/r/{self.run.id}/start", {"lang": "cs", **fields})
        self.html = text(response)
        return response

    def hidden(self):
        """What a browser sends for the values carried from the quiz page."""
        names = ("participant_name", "participant_email")
        return {
            name: field(self.html, name)
            for name in names
            if f'type="hidden" name="{name}" value="' in self.html
        }

    def form(self, **fields):
        return self.hidden() | {
            "attempt_token": field(self.html, "attempt_token"),
            "submission_key": field(self.html, "submission_key"),
            "lang": "cs",
            **fields,
        }

    def submit(self, htmx=False, **fields):
        attempt_id = self.html.split("/a/")[1].split("/")[0]
        extra = {"headers": {"HX-Request": "true"}} if htmx else {}
        response = self.client.post(f"/a/{attempt_id}/submit", self.form(**fields), **extra)
        if response.status_code == 200:
            self.result = text(response)
        return response


def test_required_name_at_end_refuses_manual_without_name():
    browser = Browser(a_run())
    browser.start()
    assert 'name="participant_name"' in browser.html
    response = browser.submit(htmx=True)
    assert response.status_code == 422
    assert response["HX-Retarget"] == "#identity-error"
    assert response["HX-Reswap"] == "innerHTML"
    assert "Zadejte své jméno." in text(response)
    assert Attempt.objects.get().status == Attempt.Status.IN_PROGRESS


def test_error_target_sits_inside_the_form_before_submit_button():
    browser = Browser(a_run())
    browser.start()
    html = browser.html
    assert html.index('id="identity-error"') < html.index('id="play-submit"')
    assert html.index('name="participant_name"') < html.index('id="play-submit"')
    assert html.index("<form") < html.index('id="identity-error"') < html.index("</form>")


def test_refused_without_script_keeps_form_and_answers():
    browser = Browser(a_run())
    browser.start()
    response = browser.submit()
    assert response.status_code == 422
    html = text(response)
    assert "Zadejte své jméno." in html
    assert 'name="participant_name"' in html
    assert 'id="play-submit"' in html
    assert Attempt.objects.get().status == Attempt.Status.IN_PROGRESS


def test_name_before_start_blocks_start():
    browser = Browser(a_run(ask_when="start"))
    page = text(FormClient().get(f"/q/{browser.run.quiz.slug}"))
    assert 'name="participant_name"' in page
    assert "Jméno a e-mail slouží jen pořadateli tohoto běhu." in page
    assert browser.start().status_code == 422
    assert Attempt.objects.count() == 0
    assert Participant.objects.count() == 0
    assert browser.start(participant_name="Jana").status_code == 200
    assert 'type="hidden" name="participant_name" value="Jana"' in browser.html
    assert browser.submit().status_code == 200
    assert Participant.objects.get().display_name == "Jana"


def test_start_checks_name_early_under_forbid():
    run = a_run(ask_when="start", duplicate_names="forbid")
    first = Browser(run)
    first.start(participant_name="Jana")
    first.submit()
    other = Browser(run)
    response = other.start(participant_name="jana")
    assert response.status_code == 409
    assert Attempt.objects.count() == 1


def test_start_form_values_do_not_reach_urls():
    run = a_run(ask_when="start")
    browser = Browser(run)
    browser.start(participant_name="Jana")
    assert "Jana" not in browser.html.split("action=")[1].split(">")[0]


def test_auto_submit_without_required_name_counts():
    browser = Browser(a_run())
    browser.start()
    response = browser.submit(auto_submit="1")
    assert response.status_code == 200
    attempt = Attempt.objects.get()
    assert attempt.status == Attempt.Status.SUBMITTED
    assert attempt.score is not None
    assert attempt.participant.display_name == ""
    assert 'action="/v/' in browser.result
    assert 'name="participant_name"' in browser.result


def result_url(browser):
    return "/v/" + browser.result.split('href="/v/')[1].split('"')[0]


def test_fill_in_later_through_result_link():
    browser = Browser(a_run(ask_email="optional"))
    browser.start()
    browser.submit(auto_submit="1")
    url = result_url(browser)
    page = text(FormClient().get(url))
    assert 'name="participant_name"' in page
    done = FormClient().post(
        url + "/identity", {"participant_name": " Jana  K ", "participant_email": "j@x.cz"}
    )
    assert done.status_code == 302
    assert done["Location"].startswith(url)
    who = Participant.objects.get()
    assert (who.display_name, who.email) == ("Jana K", "j@x.cz")
    assert 'name="participant_name"' not in text(FormClient().get(url))


def test_fill_in_changes_only_missing_fields():
    browser = Browser(a_run(ask_email="required"))
    browser.start()
    browser.submit(auto_submit="1", participant_name="Jana", participant_email="")
    url = result_url(browser)
    FormClient().post(
        url + "/identity", {"participant_name": "Jiná", "participant_email": "j@x.cz"}
    )
    who = Participant.objects.get()
    assert (who.display_name, who.email) == ("Jana", "j@x.cz")


def test_fill_in_refused_with_message_keeps_form():
    run = a_run(duplicate_names="forbid")
    first = Browser(run)
    first.start()
    first.submit(participant_name="Jana")
    second = Browser(run)
    second.start()
    second.submit(auto_submit="1", participant_name="jana")
    response = FormClient().post(result_url(second) + "/identity", {"participant_name": "JANA"})
    assert response.status_code == 200
    assert "Toto jméno už se v tomto běhu používá." in text(response)
    assert 'name="participant_name"' in text(response)
    assert Participant.objects.filter(display_name="").count() == 1


def test_fill_in_refused_after_archive():
    run = a_run()
    browser = Browser(run)
    browser.start()
    browser.submit(auto_submit="1")
    url = result_url(browser)
    authoring.close_run(run, admin_id=ADMIN_ID)
    run_schedule.archive(run, admin_id=ADMIN_ID)
    response = FormClient().post(url + "/identity", {"participant_name": "Jana"})
    assert response.status_code == 200
    assert "Tento běh je archivovaný" in text(response)
    assert Participant.objects.get().display_name == ""


def test_fill_in_with_bad_token_gives_the_one_answer():
    response = FormClient().post("/v/nonsense/identity", {"participant_name": "Jana"})
    assert response.status_code == 200
    assert "Tento odkaz nefunguje." in text(response)


def test_fill_in_needs_csrf_token():
    browser = Browser(a_run())
    browser.start()
    browser.submit(auto_submit="1")
    guarded = FormClient(enforce_csrf_checks=True)
    assert (
        guarded.post(result_url(browser) + "/identity", {"participant_name": "J"}).status_code
        == 403
    )


def test_duplicate_forbid_refuses_manual():
    run = a_run(duplicate_names="forbid")
    first = Browser(run)
    first.start()
    assert first.submit(participant_name="Žába  Ok").status_code == 200
    second = Browser(run)
    second.start()
    response = second.submit(htmx=True, participant_name="žába ok")
    assert response.status_code == 409
    assert response["HX-Retarget"] == "#identity-error"
    assert Attempt.objects.filter(status=Attempt.Status.IN_PROGRESS).count() == 1


def test_duplicate_allow_accepts():
    run = a_run(duplicate_names="allow")
    for _ in range(2):
        browser = Browser(run)
        browser.start()
        assert browser.submit(participant_name="Žába").status_code == 200


def test_auto_submit_taken_name_drops_name():
    run = a_run(duplicate_names="forbid")
    first = Browser(run)
    first.start()
    first.submit(participant_name="Jana")
    second = Browser(run)
    second.start()
    assert second.submit(auto_submit="1", participant_name="Jana").status_code == 200
    assert Participant.objects.filter(display_name="").count() == 1
    assert 'name="participant_name"' in second.result


def test_invalid_email_refused():
    browser = Browser(a_run(ask_email="optional"))
    browser.start()
    response = browser.submit(htmx=True, participant_name="Jana", participant_email="nope")
    assert response.status_code == 422
    assert Attempt.objects.get().status == Attempt.Status.IN_PROGRESS


def test_too_long_name_refused():
    browser = Browser(a_run())
    browser.start()
    assert browser.submit(htmx=True, participant_name="x" * 41).status_code == 422


def test_fields_carry_privacy_link():
    browser = Browser(a_run())
    browser.start()
    assert "Jméno a e-mail slouží jen pořadateli tohoto běhu." in browser.html
    assert 'href="/privacy?lang=cs"' in browser.html


def test_no_fields_when_nothing_is_asked():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    browser = Browser(run)
    browser.start()
    assert "participant_name" not in browser.html
    assert browser.submit().status_code == 200
    assert Participant.objects.count() == 0


def test_name_and_email_are_not_logged(caplog):
    caplog.set_level("DEBUG")
    browser = Browser(a_run(ask_email="optional"))
    browser.start()
    browser.submit(participant_name="Tajnajana", participant_email="tajne@x.cz")
    assert "Tajnajana" not in caplog.text
    assert "tajne@x.cz" not in caplog.text


def test_refused_fill_in_logs_no_token(caplog):
    caplog.set_level("DEBUG")
    run = a_run(duplicate_names="forbid", ask_email="optional")
    first = Browser(run)
    first.start()
    first.submit(participant_name="Jana")
    second = Browser(run)
    second.start()
    second.submit(auto_submit="1", participant_name="Jana")
    url = result_url(second)
    token = url.split("/v/")[1]
    FormClient().post(url + "/identity", {"participant_name": "Jana"})
    FormClient().post(url + "/identity", {"participant_name": "Eva", "participant_email": "x"})
    authoring.close_run(run, admin_id=ADMIN_ID)
    run_schedule.archive(run, admin_id=ADMIN_ID)
    FormClient().post(url + "/identity", {"participant_name": "Eva"})
    assert token not in caplog.text
    assert "/identity" not in caplog.text


def test_optional_blank_shows_no_form():
    browser = Browser(a_run(ask_name="optional", ask_email="optional"))
    browser.start()
    browser.submit()
    assert "participant_name" not in browser.result
    assert 'href="/v/' not in browser.result
    attempt = Attempt.objects.get()
    from app.domain import tokens

    url = f"/v/{tokens.issue_result(attempt.id)}"
    assert "participant_name" not in text(FormClient().get(url))


def test_required_blank_shows_form_on_private_link():
    browser = Browser(a_run())
    browser.start()
    browser.submit(auto_submit="1")
    assert 'name="participant_name"' in text(FormClient().get(result_url(browser)))


def test_name_dropped_as_taken_shows_form_even_when_optional_and_fill_in_clears_it():
    run = a_run(ask_name="optional", duplicate_names="forbid")
    first = Browser(run)
    first.start()
    first.submit(participant_name="Jana")
    second = Browser(run)
    second.start()
    second.submit(auto_submit="1", participant_name="jana")
    assert Participant.objects.get(display_name="").name_dropped
    assert 'name="participant_name"' in second.result
    url = result_url(second)
    FormClient().post(url + "/identity", {"participant_name": "Eva"})
    who = Participant.objects.get(display_name="Eva")
    assert not who.name_dropped
    assert 'name="participant_name"' not in text(FormClient().get(url))


def test_start_without_identity_creates_no_participant_and_finds_none():
    from app.domain import participants

    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    assert participants.find(run, "") is None
    Browser(run).start()
    assert Participant.objects.count() == 0


def test_responses_echoing_name_and_email_are_not_cached():
    browser = Browser(a_run(ask_when="start", ask_email="optional"))
    response = browser.start(participant_name="Jana", participant_email="j@x.cz")
    assert 'value="Jana"' in browser.html
    assert response["Cache-Control"] == "private, no-store"
    htmx = browser.submit(htmx=True, participant_name="Jana", participant_email="bad")
    assert htmx.status_code == 422
    assert htmx["Cache-Control"] == "private, no-store"
    browser.start(participant_name="Jana")
    plain = browser.submit(participant_email="bad")
    assert plain.status_code == 422
    assert plain["Cache-Control"] == "private, no-store"


def test_result_with_fill_in_form_is_not_cached():
    browser = Browser(a_run())
    browser.start()
    response = browser.submit(auto_submit="1")
    assert 'name="participant_name"' in browser.result
    assert response["Cache-Control"] == "private, no-store"
