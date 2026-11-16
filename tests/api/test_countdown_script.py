"""AC-141: the automatic submission is repeated after a lost answer (TD-022, TD-083).

There is no JavaScript harness (TD-039): the script is read as text, and the countdown box is
rendered in the three languages. The repeating itself is checked in a browser walkthrough.
"""

import re
from html import unescape
from pathlib import Path

import pytest
from django.template.loader import render_to_string
from django.utils import translation

SCRIPT = Path(__file__).resolve().parents[2] / "app/api/assets/countdown.js"
NOTE = {
    "en": "Sending your answers again.",
    "cs": "Odpovědi se odesílají znovu.",
    "uk": "Відповіді надсилаються повторно.",
}


def script():
    return SCRIPT.read_text(encoding="utf-8")


def test_the_script_repeats_on_send_error_response_error_and_429():
    code = script()
    for event in ("htmx:sendError", "htmx:responseError", "htmx:afterRequest"):
        assert f'"{event}"' in code
    assert "[1000, 1000, 1500, 3000, 6000, 12000]" in code
    assert "Retry-After" in code
    assert "getResponseHeader" in code
    assert "status >= 500" in code
    assert "429" in code
    # Only after the automatic submission began, and only for this form.
    assert code.count("state.sent") >= 3
    assert "event.target" in code


def test_the_repeat_is_the_same_submission_with_the_same_key():
    code = script()
    assert "form.requestSubmit()" in code
    assert "retries" not in code
    assert "createElement" in code and code.count("createElement") == 1


def test_the_automatic_submission_has_no_request_timeout():
    """A timeout cuts a request the server may still be storing; the repeat would then be refused
    as late while the first send commits. A hang cannot be repeated inside the margin anyway."""
    code = script()
    for word in ("detail.timeout", "REQUEST_TIMEOUT", "htmx:timeout", "htmx:configRequest"):
        assert word not in code
    assert not re.search(r"\.timeout\s*=", code)


def test_the_first_three_repeats_fall_inside_the_margin_before_the_limit():
    code = script()
    repeats = re.search(r"var REPEAT_MS = \[([\d, ]+)\];", code)
    margin = re.search(r"var SEND_BEFORE_SECONDS = (\d+);", code)
    assert repeats and margin
    waits = [int(number) for number in repeats.group(1).split(",")]
    assert len(waits) == 6
    assert sum(waits[:3]) < int(margin.group(1)) * 1000, (
        "a repeat after the limit is rejected by the server (attempt_expired): the first repeats"
        " must fall inside the margin the script sends before the end"
    )


@pytest.mark.parametrize("locale", ["cs", "en", "uk"])
def test_the_countdown_box_has_the_waiting_note_in_three_languages(locale):
    with translation.override(locale):
        html = render_to_string("public/_countdown.html", {"time_left": 90})
    match = re.search(r"<p[^>]*data-countdown-retry[^>]*></p>", html)
    assert match, html
    tag = match.group(0)
    # An empty live region that stays in the page: the script writes the text into it, which is
    # announced, where taking `hidden` off an element is not reliably announced.
    assert " hidden" not in tag
    assert 'role="status"' in tag
    text = re.search(r'data-text="([^"]*)"', tag)
    assert text and unescape(text.group(1)) == NOTE[locale]
    assert html.index("data-countdown-retry") < html.rindex("</div>")


def test_the_script_writes_and_clears_the_note_text():
    code = script()
    assert "dataset.text" in code
    assert 'shown ? note.dataset.text : ""' in code


def test_the_last_repeat_that_times_out_still_says_so_on_the_page():
    code = (SCRIPT.parent / "play.js").read_text(encoding="utf-8")
    assert 'addEventListener("htmx:timeout", showNetworkError)' in code


def test_the_waiting_note_is_on_its_own_line_and_empty_takes_no_space():
    theme = Path(__file__).resolve().parents[2] / "app/plugins/theme_default/assets/theme.css"
    css = theme.read_text(encoding="utf-8")
    block = css[css.index(".countdown-note {") :].split("}")[0]
    assert "flex-basis: 100%" in block
    assert ".countdown-note:empty" in css


def test_a_background_poll_does_not_clear_the_message_of_the_answer():
    code = (SCRIPT.parent / "play.js").read_text(encoding="utf-8")
    handler = code[code.index('addEventListener("htmx:beforeRequest"') :]
    assert 'closest("#revision-notice")' in handler
    assert handler.index('closest("#revision-notice")') < handler.index('textContent = ""')


def test_the_polling_element_the_script_skips_is_in_the_questions():
    template = SCRIPT.parent.parent / "jinja2/public/_questions.html"
    html = template.read_text(encoding="utf-8")
    assert re.search(r'<div id="revision-notice"[^>]*hx-trigger="every ', html)
