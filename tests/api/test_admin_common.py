from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from django.http import Http404
from django.test import RequestFactory

from app.api import admin_common


def request_of(**attrs):
    request = RequestFactory().get("/")
    for name, value in attrs.items():
        setattr(request, name, value)
    return request


def test_admin_id_is_the_user_pk_as_text():
    pk = uuid4()
    assert admin_common.admin_id(request_of(user=SimpleNamespace(pk=pk))) == str(pk)


def test_uuid_or_404():
    pk = uuid4()
    assert admin_common.uuid_or_404(str(pk)) == pk
    for bad in ("", "x", "1234"):
        with pytest.raises(Http404):
            admin_common.uuid_or_404(bad)


def test_plain_drops_exponent_and_trailing_zeros():
    assert admin_common.plain(Decimal("2.50")) == "2.5"
    assert admin_common.plain(Decimal("100")) == "100"
    assert admin_common.plain(Decimal("0.0")) == "0"
    assert admin_common.plain(None) == ""
    assert admin_common.plain(None, none="0") == "0"


def test_locale_of_reads_the_request_locale():
    assert admin_common.locale_of(request_of(locale="uk")) == "uk"


CODES = (
    "start_in_past",
    "deadline_before_start",
    "already_planned",
    "not_planned",
    "deadline_too_soon",
    "not_open",
    "data_deleted",
    "not_ended",
)


def test_refusal_knows_every_run_code_and_falls_back():
    general = admin_common.refusal("nope")
    texts = {admin_common.refusal(code) for code in CODES}
    assert len(texts) == len(CODES)
    assert general not in texts


def test_confirm_page_leaves_out_what_was_not_given(monkeypatch):
    seen = {}

    def fake_page(request, template, context, locale, **kwargs):
        seen.update(template=template, context=context, locale=locale)
        return "response"

    monkeypatch.setattr(admin_common, "page", fake_page)
    request = request_of(locale="cs")
    assert admin_common.confirm_page(request, message="m", action="/a") == "response"
    assert seen == {
        "template": "admin/confirm.html",
        "context": {"message": "m", "action": "/a"},
        "locale": "cs",
    }
    admin_common.confirm_page(
        request, message="m", action="/a", cancel="/c", quiz="q", hidden={"k": "v"}, repeated=[]
    )
    assert seen["context"] == {
        "message": "m",
        "action": "/a",
        "cancel": "/c",
        "quiz": "q",
        "hidden": {"k": "v"},
        "repeated": [],
    }
