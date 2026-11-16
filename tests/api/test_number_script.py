"""AC-142: a number field warns that "1,000" is read as one (TD-018).

There is no JavaScript harness (TD-039): the script is read as text, its pattern is taken from the
file and evaluated with Python's `re`, and the field is rendered in the three languages. The note
itself is checked in a browser walkthrough.
"""

import re
from decimal import Decimal
from html import unescape
from pathlib import Path

import pytest
from django.template.loader import render_to_string
from django.utils import translation

from app.api.public import SERVED_ASSETS
from app.api.rendering import SCRIPTS
from app.plugins.questions.number.plugin import parse_number

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "app/api/assets/number.js"
NOTE = {
    "en": (
        "“{value}” is read as {read}: a comma or a dot is a decimal sign. "
        "Type a large number without a separator."
    ),
    "cs": (
        "„{value}“ se čte jako {read}: čárka i tečka jsou desetinné. "
        "Velké číslo pište bez oddělovače."
    ),
    "uk": (
        "«{value}» читається як {read}: кома й крапка — десяткові роздільники. "
        "Велике число вводьте без роздільника."
    ),
}


def script():
    return SCRIPT.read_text(encoding="utf-8")


def pattern():
    literals = re.findall(r"^\s*var THOUSANDS = /(.+)/;$", script(), re.MULTILINE)
    assert len(literals) == 1
    return re.compile(literals[0])


@pytest.mark.parametrize("text", ["1,000", "1.000", "-2,500", "999.999", "0,100"])
def test_the_script_matches_exactly_one_separator_and_three_digits(text):
    assert pattern().search(text)


@pytest.mark.parametrize(
    "text", ["1,5", "10,00", "1.000.000", "1000", "", "12,3456", "1,000a", "abc", "1 000", "1,,000"]
)
def test_the_script_leaves_other_texts_alone(text):
    assert not pattern().search(text)


def test_the_script_trims_the_text_and_never_blocks_sending():
    code = script()
    assert ".trim()" in code
    assert '"input"' in code and '"DOMContentLoaded"' in code and '"htmx:afterSwap"' in code
    assert "preventDefault" not in code
    assert "requestSubmit" not in code
    assert "setCustomValidity" not in code
    assert "disabled" not in code
    assert "dataset.text" in code


@pytest.mark.parametrize("locale", ["cs", "en", "uk"])
def test_the_field_has_the_note_in_three_languages(locale):
    with translation.override(locale):
        html = render_to_string("number/public.html", {"q": {"id": "q1", "prompt": "How many?"}})
    match = re.search(r"<p[^>]*data-number-note[^>]*></p>", html)
    assert match, html
    tag = match.group(0)
    # An empty live region that stays in the page; the script writes the text and clears it.
    assert " hidden" not in tag
    assert 'role="status"' in tag
    text = re.search(r'data-text="([^"]*)"', tag)
    assert text and unescape(text.group(1)) == NOTE[locale]
    assert html.index("<input") < html.index("data-number-note")
    # The note carries no number of its own: what the field is read as is filled in by the script.
    assert not re.search(r"\d", text.group(1))


def reading(typed):
    """The reading rule of the script, mirrored: String(parseFloat(typed.replace(",", "."))), with
    the dot put back as a comma when the participant typed a comma.

    parseFloat and Decimal agree on the texts the pattern lets through; JavaScript prints 1 and
    not 1.0, and -2.5 and not -2.50, which Decimal.normalize() gives too for these.
    """
    read = format(Decimal(typed.replace(",", ".")).normalize(), "f")
    return read.replace(".", ",") if "," in typed else read


def test_the_script_reads_with_the_separator_the_participant_typed():
    code = script()
    assert 'replace("{value}", text)' in code
    assert 'replace("{read}", read)' in code
    assert 'String(parseFloat(text.replace(",", ".")))' in code
    assert 'text.indexOf(",") !== -1' in code
    assert code.count("parseFloat") == 1


@pytest.mark.parametrize(
    "typed,read",
    [
        ("1,000", "1"),
        ("1.000", "1"),
        ("2,500", "2,5"),
        ("2.500", "2.5"),
        ("-2,500", "-2,5"),
        ("-3.250", "-3.25"),
    ],
)
def test_the_note_says_what_the_server_reads(typed, read):
    assert reading(typed) == read
    assert Decimal(read.replace(",", ".")) == parse_number(typed)


def test_the_script_is_loaded_on_the_pages():
    assert "number.js" in SCRIPTS
    assert "number.js" in SERVED_ASSETS


def test_the_server_still_grades_1_000_as_one():
    assert parse_number("1,000") == Decimal(1)
    assert parse_number("1.000") == Decimal(1)
