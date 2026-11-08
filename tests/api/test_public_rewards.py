"""AC-91: what a participant sees of rewards on the public pages.

The result page and the private link show what the participant holds, with its name, description
and claim instructions in the page's language, else in the quiz's default language. The quiz page
names the run's rewards without their internals. The scoreboard page names the winners of a draw
only when the admin published them, by nickname or anonymous label, never by e-mail.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.contracts import ASK_EMAIL, REWARD_SOURCE, REWARD_THRESHOLDS, SCOREBOARD_VISIBILITY
from app.domain import attempts, authoring, draws, participants, rewards, settings, tokens
from app.domain.models import Attempt, RewardEntitlement
from tests.domain.helpers import ADMIN_ID, OPTION_A, published_quiz
from tests.support.client import FormClient
from tests.support.clock import freeze

pytestmark = pytest.mark.django_db
NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)
LOCALES = ("cs", "en", "uk")


@pytest.fixture(autouse=True)
def at_ten(monkeypatch):
    freeze(monkeypatch, NOW)


def text(response):
    return response.content.decode()


def texts(name, description="", claim="", locales=LOCALES):
    return {
        locale: {
            "name": f"{name} {locale}",
            "description": f"{description} {locale}" if description else "",
            "claim": f"{claim} {locale}" if claim else "",
        }
        for locale in locales
    }


def threshold(percent=50, **given):
    return rewards.RuleData(
        kind="threshold",
        threshold_unit="percent",
        threshold_value=Decimal(percent),
        texts=given.get("texts") or texts("Diplom", "Za úspěch", "Vyzvedněte u stolku"),
    )


def drawn(name="Hlavní cena", winners=1, alternates=0):
    return rewards.RuleData(
        kind="draw",
        winners=winners,
        alternates=alternates,
        texts={"cs": {"name": name, "description": "", "claim": "Napište nám"}},
    )


def open_with(*rules, locales=LOCALES, **chosen):
    quiz = published_quiz("kviz", locales=locales)
    for data in rules:
        rewards.save_rule(quiz, data, rule=None, admin_id=ADMIN_ID)
    settings.set_override(REWARD_SOURCE, quiz, "quiz", admin_id=ADMIN_ID)
    return authoring.open_run(quiz, admin_id=ADMIN_ID, **chosen)


def field(html, name):
    return html.split(f'name="{name}" value="')[1].split('"')[0]


def play_page(run, lang="en"):
    """Starts and submits through HTTP; returns the result fragment."""
    client = FormClient()
    started = client.post(f"/r/{run.id}/start", {"lang": lang})
    html = text(started)
    attempt_id = html.split("/a/")[1].split("/")[0]
    question_id = run.current_revision.snapshot_json["questions"][0]["id"]
    return client.post(
        f"/a/{attempt_id}/submit",
        {
            "attempt_token": field(html, "attempt_token"),
            "submission_key": field(html, "submission_key"),
            "lang": lang,
            f"{question_id}:options[]": OPTION_A,
        },
    )


def play(run, number, name="", email=None):
    who = participants.find_or_create(run, f"key-{number:016d}")
    type(who).objects.filter(pk=who.pk).update(display_name=name, email=email)
    started = attempts.start(run, participant=who)
    questions = attempts.questions_of(started.attempt)
    answers = {question["id"]: {"options": [OPTION_A]} for question in questions}
    attempts.submit(started.attempt.id, started.token, answers, f"submit-{number:010d}")
    who.refresh_from_db()
    return who


def section(html, marker='class="rewards', end="</div>"):
    """Only the section itself: the rest of the page holds ids, which may contain any digits."""
    assert marker in html
    found = html[html.index(marker) :]
    return found[: found.index(end)]


def test_result_page_shows_entitlement_with_claim_in_attempt_language():
    run = open_with(threshold())
    html = text(play_page(run, "en"))
    found = section(html)
    assert "Diplom en" in found and "Za úspěch en" in found and "Vyzvedněte u stolku en" in found
    assert "Diplom cs" not in found and "Granted" in found
    uk = section(text(play_page(run, "uk")))
    assert "Diplom uk" in uk and "Vyzvedněte u stolku uk" in uk
    # Handed over is said in words too.
    entitlement = RewardEntitlement.objects.order_by("created_at").first()
    rewards.hand_over(entitlement, admin_id=ADMIN_ID)
    (shown,) = rewards.shown(entitlement.participant, "en")
    assert shown == rewards.ShownReward(
        name="Diplom en",
        description="Za úspěch en",
        claim="Vyzvedněte u stolku en",
        status="handed_over",
    )


def test_claim_text_is_escaped_on_the_result_page():
    claim = {"cs": {"name": "Cena", "description": "", "claim": "<b>x</b>"}}
    run = open_with(threshold(texts=claim))
    html = text(play_page(run, "cs"))
    found = section(html)
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in found


def test_private_link_says_handed_over_in_words():
    run = open_with(threshold())
    who = play(run, 1, "Alena")
    attempt = Attempt.objects.get(participant=who)
    link = f"/v/{tokens.issue_result(attempt.id)}?lang=en"
    assert "Granted" in section(text(FormClient().get(link)))
    entitlement = RewardEntitlement.objects.get(participant=who)
    rewards.hand_over(entitlement, admin_id=ADMIN_ID)
    found = section(text(FormClient().get(link)))
    assert "Handed over" in found and "Granted" not in found


def test_private_link_shows_draw_win_after_draw():
    run = open_with(drawn(), rules={ASK_EMAIL: "optional"})
    who = play(run, 1, "Alena", "alena@example.org")
    attempt = Attempt.objects.get(participant=who)
    link = f"/v/{tokens.issue_result(attempt.id)}?lang=cs"
    assert 'class="rewards' not in text(FormClient().get(link))
    authoring.close_run(run, admin_id=ADMIN_ID)
    rule = rewards.rules_of(run)[0]
    draws.draw(rule, admin_id=ADMIN_ID)
    found = section(text(FormClient().get(link)))
    assert "Hlavní cena" in found and "Napište nám" in found and "Udělená" in found
    assert "alena@example.org" not in found


def test_nothing_shown_without_rules():
    run = open_with()
    html = text(play_page(run, "en"))
    assert "Your score" in html and 'class="rewards' not in html
    assert rewards.shown(None, "en") == []
    page = text(FormClient().get(f"/q/{run.quiz.slug}/r/{run.id}?lang=en"))
    assert 'class="rewards' not in page
    assert rewards.offered(run, "en") == [] and rewards.public_winners(run, "en") == []


def test_missing_translation_falls_back_and_name_escaped():
    only_cs = {"cs": {"name": "<b>Cena</b>", "description": "Popis", "claim": "Vyzvedněte"}}
    partly = texts("Medaile", "Za účast", "U pokladny", locales=("cs",)) | {
        "uk": {"name": "Медаль", "description": "", "claim": ""}
    }
    run = open_with(
        threshold(texts=only_cs),
        threshold(40, texts=partly),
        rewards={REWARD_THRESHOLDS: "all"},
    )
    html = text(play_page(run, "uk"))
    found = section(html)
    assert "<b>Cena</b>" not in html and "&lt;b&gt;Cena&lt;/b&gt;" in found
    assert "Vyzvedněte" in found
    # Each field falls back on its own: the uk name, the cs description and claim.
    assert "Медаль" in found and "Medaile cs" not in found
    assert "Za účast cs" in found and "U pokladny cs" in found
    # A text missing in every language stays empty.
    run.reward_rules.filter(position=1).update(texts_json={"en": {"name": "Prize"}})
    participant = RewardEntitlement.objects.first().participant
    first = rewards.shown(participant, "uk")[0]
    assert first.name == "" and first.claim == ""


def test_quiz_page_lists_rules_without_thresholds_internals():
    run = open_with(threshold(73), drawn(winners=3, alternates=4))
    html = text(FormClient().get(f"/q/{run.quiz.slug}/r/{run.id}?lang=en"))
    found = section(html)
    assert "Diplom en" in found and "Za úspěch en" in found
    # The draw has no en text, so the quiz's default language names it.
    assert "Hlavní cena" in found
    # Claim instructions, threshold and counts are internals.
    assert "Vyzvedněte" not in found and "Napište" not in found and "73" not in found
    assert rewards.offered(run, "en") == [("Diplom en", "Za úspěch en"), ("Hlavní cena", "")]


def test_published_winners_on_scoreboard_without_email():
    run = open_with(
        drawn(winners=2),
        rules={ASK_EMAIL: "optional"},
        results={SCOREBOARD_VISIBILITY: "hidden"},
    )
    alena = play(run, 1, "Alena", "alena@example.org")
    nameless = play(run, 2, "", "nikdo@example.org")
    authoring.close_run(run, admin_id=ADMIN_ID)
    rule = rewards.rules_of(run)[0]
    draws.draw(rule, admin_id=ADMIN_ID)
    draws.set_public(rule, True, admin_id=ADMIN_ID)
    response = FormClient().get(f"/q/{run.quiz.slug}/r/{run.id}/scoreboard?lang=en")
    html = text(response)
    # The board stays hidden, the winners are listed below its reason.
    assert "The scoreboard is not public." in html
    found = section(html, 'class="card winners', "</section>")
    assert "Hlavní cena" in found and "Alena" in found and "Player 2" in found
    assert "@example.org" not in html
    assert str(alena.id) not in html and str(nameless.id) not in html
    ((name, people),) = rewards.public_winners(run, "en")
    assert name == "Hlavní cena" and sorted(people) == ["Alena", "Player 2"]


def test_unpublished_winners_absent():
    run = open_with(drawn(), rules={ASK_EMAIL: "optional"})
    play(run, 1, "Alena")
    authoring.close_run(run, admin_id=ADMIN_ID)
    rule = rewards.rules_of(run)[0]
    url = f"/q/{run.quiz.slug}/r/{run.id}/scoreboard?lang=en"
    draws.set_public(rule, True, admin_id=ADMIN_ID)  # published, but nothing drawn yet
    assert 'class="card winners' not in text(FormClient().get(url))
    draws.draw(rule, admin_id=ADMIN_ID)
    draws.set_public(rule, False, admin_id=ADMIN_ID)
    html = text(FormClient().get(url))
    assert 'class="card winners' not in html and "Hlavní cena" not in html
    assert rewards.public_winners(run, "en") == []
