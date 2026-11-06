import pytest
from django import forms
from django.http import HttpResponse
from django.test import RequestFactory

from app.api import i18n
from tests.domain.helpers import open_quiz_run


def request(query="", accept=None):
    headers = {"Accept-Language": accept} if accept else {}
    return RequestFactory().get(f"/{query}", headers=headers)


def test_negotiate_prefers_query_then_accept_language_then_default():
    allowed = ["cs", "en", "uk"]
    assert i18n.negotiate(request("?lang=uk", "en"), allowed, "cs") == "uk"
    assert i18n.negotiate(request("", "en-GB,cs;q=0.5"), allowed, "cs") == "en"
    assert i18n.negotiate(request("", "uk-UA"), allowed, "cs") == "uk"
    assert i18n.negotiate(request(), allowed, "cs") == "cs"


def test_negotiate_respects_quality_values():
    assert i18n.negotiate(request("", "en;q=0.3,uk;q=0.9"), ["en", "uk"], "en") == "uk"


@pytest.mark.parametrize(
    ("query", "accept"),
    [("?lang=de", None), ("?lang=", None), ("", "de"), ("", ";;;=q,"), ("?lang=<x>", "fr;q=x")],
)
def test_negotiate_ignores_unsupported_values(query, accept):
    assert i18n.negotiate(request(query, accept), ["cs", "uk"], "uk") == "uk"


def test_negotiate_reads_language_from_form():
    post = RequestFactory().post("/", {"lang": "uk"})
    assert i18n.negotiate(post, ["cs", "uk"], "cs") == "uk"


@pytest.mark.django_db
def test_language_does_not_leak_to_next_request(client):
    run = open_quiz_run(locales=("cs", "uk"))
    assert b'<html lang="uk"' in client.get(f"/q/{run.quiz.slug}?lang=uk").content
    assert b'<html lang="cs"' in client.get("/").content


def test_django_validation_messages_follow_language():
    def view(request):
        return HttpResponse(str(forms.Field.default_error_messages["required"]))

    middleware = i18n.LocaleMiddleware(view)
    czech = middleware(request("?lang=cs")).content.decode()
    english = middleware(request("?lang=en")).content.decode()
    assert english == "This field is required."
    assert czech != english
