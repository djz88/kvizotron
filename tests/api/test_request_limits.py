"""What a request may look like, and which routes are protected by what (TD-009, security.md)."""

import re
from pathlib import Path
from uuid import uuid7

import pytest
from django.test import Client
from django.urls import get_resolver, reverse

import app.api
from app.api import admin_urls
from app.domain.models import Attempt
from tests.domain.helpers import make_quiz, open_quiz_run
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
TEMPLATES = Path(app.api.__file__).parent / "jinja2"
BAD_CHARSET = "multipart/form-data; boundary=x; charset=nonsense"
ARGUMENTS = {
    "module_id": "question.number",
    "link_id": uuid7(),
    "answer_id": uuid7(),
    "job_id": uuid7(),
    "quiz_id": uuid7(),
    "run_id": uuid7(),
    "question_id": uuid7(),
    "revision_no": 1,
    "bank_id": uuid7(),
    "folder_id": uuid7(),
    "participant_id": uuid7(),
    "draw_id": "x",
    "rule_id": uuid7(),
    "entitlement_id": uuid7(),
    "name": "x.csv",
    "slug": "x",
    "attempt_id": uuid7(),
    "asset_id": uuid7(),
    "admin_id": uuid7(),
    "token": "x",
}


def test_multipart_is_refused_on_public_start():
    run = open_quiz_run()
    response = Client().post(f"/r/{run.id}/start", {"lang": "cs"})
    assert response.status_code == 415
    assert not Attempt.objects.exists()


def test_multipart_with_invalid_charset_is_not_a_server_error():
    response = Client().generic("POST", "/admin/login", b"x", content_type=BAD_CHARSET)
    assert response.status_code == 415


def test_form_still_works():
    run = open_quiz_run()
    assert FormClient().post(f"/r/{run.id}/start", {"lang": "cs"}).status_code == 200


def test_get_is_not_affected():
    assert Client().get("/", content_type=BAD_CHARSET).status_code == 200


def test_only_play_routes_are_csrf_exempt():
    exempt = {
        pattern.name
        for pattern in get_resolver().url_patterns
        if getattr(getattr(pattern, "callback", None), "csrf_exempt", False)
    }
    assert exempt == {"start", "resume", "submit", "switch", "check", "attempt_time"}


@pytest.mark.parametrize("pattern", admin_urls.urlpatterns, ids=lambda p: p.name)
def test_every_admin_route_refuses_post_without_csrf_token(admin_user, pattern):
    names = pattern.pattern.converters
    client = FormClient(enforce_csrf_checks=True)
    client.force_login(admin_user)
    url = reverse(pattern.name, kwargs={name: ARGUMENTS[name] for name in names})
    assert client.post(url).status_code == 403


@pytest.mark.parametrize(
    "template", sorted((TEMPLATES / "admin").glob("*.html")), ids=lambda path: path.name
)
def test_every_admin_form_carries_a_csrf_token(template):
    html = template.read_text()
    assert len(re.findall(r'method="post"', html)) == html.count("{{ csrf_input }}")


def multipart(client, path):
    return client.post(path, {"prompt_cs": "Q"})  # plain Client sends multipart


def test_multipart_allowed_only_on_question_editor_routes(admin_user):
    quiz = make_quiz()
    client = Client()
    client.force_login(admin_user)
    new = f"/admin/quizzes/{quiz.id}/questions/new?type=choice"
    assert multipart(client, new).status_code == 302  # the view saved the question
    edit = f"/admin/quizzes/{quiz.id}/questions/abc/edit"
    assert multipart(client, edit).status_code == 404  # reached the view
    for refused in (
        f"/admin/quizzes/{quiz.id}/edit",
        f"/admin/quizzes/{quiz.id}/questions/abc/delete",
        f"/admin/quizzes/{quiz.id}/questions/new/extra",
        "/admin/settings",
        "/",
    ):
        assert multipart(client, refused).status_code == 415, refused


def test_anonymous_multipart_to_the_editor_gets_no_upload():
    quiz = make_quiz()
    response = multipart(Client(), f"/admin/quizzes/{quiz.id}/questions/new?type=choice")
    assert response.status_code == 415


def test_multipart_with_invalid_charset_to_the_editor_is_not_a_server_error(admin_user):
    quiz = make_quiz()
    client = Client()
    client.force_login(admin_user)
    response = client.generic(
        "POST",
        f"/admin/quizzes/{quiz.id}/questions/new?type=choice",
        b"x",
        content_type="multipart/form-data; boundary=x; charset=nonsense",
    )
    assert response.status_code == 415


BUCKETS = {"login", "code", "submit", "start", "login_address"}
READS_ONLY = (
    "unlimited: only reads, so it writes no row or file, and any body sent to it is ignored"
)
LIMITS_OF_ROUTES: dict[str, str] = {
    "start": "start",  # creates an attempt row, and a participant row for a new browser
    "submit": "submit",  # scores an attempt and stores the answers and photos sent with it
    "run_code": "code",  # a wrong code counts; a right one only sets a signed cookie
    "resume": (
        "unlimited: needs the signed attempt token and only issues a fresh token for an attempt"
        " that already exists, so it writes no row, file or cookie"
    ),
    "switch": (
        "unlimited: needs the signed attempt token and creates at most one replacement attempt"
        " per change of the run's current revision (publishing, or a return to an older revision),"
        " because the replacement is already on the current revision"
    ),
    "check": (
        "unlimited: needs the signed attempt token and only renders one question's reveal,"
        " storing nothing"
    ),
    "attempt_time": (
        "unlimited: needs the signed attempt token and only returns the seconds left,"
        " writing nothing"
    ),
    "result_identity": (
        "unlimited: needs the signed result token and fills in only the name or e-mail still"
        " missing on an existing participant, so it creates no row and a second call changes"
        " nothing"
    ),
    "landing": READS_ONLY,
    "how_it_works": READS_ONLY,
    "about": READS_ONLY,
    "privacy": READS_ONLY,
    "quiz": READS_ONLY,
    "quiz_run": READS_ONLY,
    "walkthrough_page": READS_ONLY,
    "walkthrough_photo": READS_ONLY,
    "scoreboard": READS_ONLY,
    "scoreboard_rows": READS_ONLY,
    "test_link": READS_ONLY,
    "result": READS_ONLY,
    "result_photo": READS_ONLY,
    "media": READS_ONLY,
    "asset": READS_ONLY,
    "theme.default:asset": READS_ONLY,
    "healthz": READS_ONLY,
}


def route_key(name, route, namespace=""):
    """The key of a route in LIMITS_OF_ROUTES: its namespaced name, else its pattern."""
    if name:
        return f"{namespace}{name}"
    if "<" in route:
        raise AssertionError(f"route {route} has a converter and no name; give it a name")
    return route


def public_routes(patterns=None, prefix="", namespace=""):
    """(name, url pattern string, converter names) of each route outside /admin/."""
    for pattern in get_resolver().url_patterns if patterns is None else patterns:
        route = prefix + str(pattern.pattern)
        if route.startswith("admin/"):
            continue
        if hasattr(pattern, "url_patterns"):  # an include
            inner = f"{namespace}{pattern.namespace}:" if pattern.namespace else namespace
            yield from public_routes(pattern.url_patterns, route, inner)
        else:
            yield route_key(pattern.name, route, namespace), route, list(pattern.pattern.converters)


def accepts_post(name, route, converters):
    """Whether a POST gets past the method check: anything but 405 means a view would act on it."""
    if name == route:  # no name to reverse: build the address from the pattern
        url = "/" + route
    else:
        url = reverse(name, kwargs={each: ARGUMENTS[each] for each in converters})
    return FormClient().post(url, {}).status_code != 405


def routes_taking_post():
    return sorted(
        {name for name, route, each in public_routes() if accepts_post(name, route, each)}
    )


def test_every_public_route_has_a_declared_limit():
    """AC-131: a public route that takes a POST has a bucket or a written reason for none."""
    undeclared = [name for name in routes_taking_post() if name not in LIMITS_OF_ROUTES]
    assert not undeclared, f"declare a limit, or why there is none, for: {undeclared}"


def test_every_declared_limit_belongs_to_a_route_that_exists():
    """AC-131: the list of limits names no route that is gone."""
    existing = {name for name, _route, _each in public_routes()}
    assert sorted(set(LIMITS_OF_ROUTES) - existing) == []


def test_every_declaration_names_a_bucket_or_gives_a_reason():
    """AC-131: a declaration is a bucket or a reason."""
    for name, limit in LIMITS_OF_ROUTES.items():
        assert limit in BUCKETS or (limit.startswith("unlimited: ") and len(limit.split()) >= 6), (
            f"{name}: {limit!r}"
        )


def test_an_unnamed_route_with_a_converter_is_refused_with_a_clear_message():
    assert route_key("", "healthz") == "healthz"
    assert route_key("start", "r/<uuid:run_id>/start", "theme.default:") == "theme.default:start"
    with pytest.raises(AssertionError, match="has a converter and no name; give it a name"):
        route_key("", "x/<slug:slug>")


def test_concurrent_submits_from_one_address_never_exceed_the_limit(settings, monkeypatch):
    """AC-130: parallel submits from one address take their slot atomically, none slips past."""
    import threading

    from app.api import rate_limit

    settings.KVZ_SUBMITS_PER_MINUTE = 5
    rate_limit.reset()
    barrier = threading.Barrier(20)
    real_allow = rate_limit.allow

    def allow_then_wait(*args, **kwargs):
        # A check-then-store limiter lets all 20 threads pass the check before any stores.
        # try_acquire never calls allow, so the fixed code is not held up here.
        result = real_allow(*args, **kwargs)
        try:
            barrier.wait(timeout=3)
        except threading.BrokenBarrierError:
            pass
        return result

    monkeypatch.setattr(rate_limit, "allow", allow_then_wait)
    statuses: list[int] = []

    def post():
        client = FormClient()
        response = client.post(f"/a/{uuid7()}/submit", {}, HTTP_X_FORWARDED_FOR="10.9.9.9")
        statuses.append(response.status_code)

    threads = [threading.Thread(target=post) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    rate_limit.reset()
    assert len(statuses) == 20
    assert sum(status != 429 for status in statuses) == 5


def test_a_wrong_code_counts_once_and_a_right_code_frees_its_slot(settings):
    """ADR-0058: only wrong codes keep a slot in the code bucket."""
    from app.api import rate_limit
    from app.domain import access_codes, authoring
    from tests.domain.helpers import ADMIN_ID, published_quiz

    settings.KVZ_CODE_ATTEMPTS_PER_MINUTE = 2
    rate_limit.reset()
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    access_codes.set_code(run, "ABCD2345", admin_id=ADMIN_ID)

    def enter(code):
        return FormClient().post(
            f"/r/{run.id}/code", {"lang": "cs", "code": code}, HTTP_X_FORWARDED_FOR="10.8.8.8"
        )

    assert enter("WRONG234").status_code == 403
    assert enter("ABCD2345").status_code == 302  # right code: its slot goes back
    assert enter("WRONG234").status_code == 403  # second wrong, still allowed
    assert enter("WRONG234").status_code == 429
    rate_limit.reset()
