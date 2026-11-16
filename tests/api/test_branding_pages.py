"""AC-94, AC-96, AC-97: the pages show the resolved branding and the Kvízotron line."""

import re
import uuid
from pathlib import Path

import pytest

from app.contracts import COLOR_PALETTE, CUSTOM_PALETTE, SCOREBOARD_VISIBILITY, BrandColours
from app.domain import attempts, authoring, branding, run_links, settings, tokens
from app.domain.models import Attempt, BrandingConfiguration
from tests.domain.helpers import ADMIN_ID, OPTION_A, published_quiz
from tests.support.client import FormClient

pytestmark = pytest.mark.django_db
THEME = Path(__file__).resolve().parents[2] / "app" / "plugins" / "theme_default" / "assets"
LOGO = str(uuid.uuid4())
COLOURS = BrandColours("#aa2255", "#2255aa")


def text(response):
    return response.content.decode()


def png_bytes():
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), "red").save(buffer, "PNG")
    return buffer.getvalue()


def brand(quiz, name="Moje škola", footer="Kontakt: škola", logo=True, custom=True):
    branding.set_texts(quiz, "name", {"cs": name}, admin_id=ADMIN_ID)
    branding.set_texts(quiz, "motto", {"cs": "Hurá do kvízu"}, admin_id=ADMIN_ID)
    branding.set_texts(quiz, "footer", {"cs": footer}, admin_id=ADMIN_ID)
    if logo:
        row = BrandingConfiguration.objects.get(quiz=quiz)
        row.assets_json = {"logo": LOGO, "hero_logo": LOGO}
        row.save()
    if custom:
        branding.set_colours(quiz, COLOURS, admin_id=ADMIN_ID)
        if quiz is None:
            settings.set_global(COLOR_PALETTE, CUSTOM_PALETTE, admin_id=ADMIN_ID)
        else:
            settings.set_override(COLOR_PALETTE, quiz, CUSTOM_PALETTE, admin_id=ADMIN_ID)


def shows_quiz_branding(html, name="Moje škola"):
    assert f"{name}</a>" in html and f"/media/{LOGO}" in html
    assert "Kontakt: škola" in html
    assert 'data-palette="custom"' in html
    assert ':root[data-palette="custom"]' in html and "--kvz-main: #" in html


def played(run):
    client = FormClient()
    html = text(client.post(f"/r/{run.id}/start", {"lang": "cs"}))
    attempt = Attempt.objects.get()
    question = attempts.questions_of(attempt)[0]
    client.post(
        f"/a/{attempt.id}/submit",
        {
            "attempt_token": html.split('name="attempt_token" value="')[1].split('"')[0],
            "submission_key": html.split('name="submission_key" value="')[1].split('"')[0],
            "lang": "cs",
            f"{question['id']}:options[]": [OPTION_A],
        },
    )
    return client, attempt, html


def test_quiz_page_and_play_show_the_quiz_branding():
    """AC-94, AC-96."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    brand(run.quiz)
    client = FormClient()
    html = text(client.get("/q/kviz"))
    shows_quiz_branding(html)
    assert "Hurá do kvízu" in html
    assert "Moje škola" in html.split("<title>")[1].split("</title>")[0]
    shows_quiz_branding(text(client.post(f"/r/{run.id}/start", {"lang": "cs"})))


def test_result_and_walkthrough_show_the_quiz_branding():
    """AC-94."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    brand(run.quiz)
    client, attempt, _html = played(run)
    shows_quiz_branding(text(client.get(f"/v/{tokens.issue_result(attempt.id)}")))


def test_scoreboard_shows_the_quiz_branding():
    """AC-94."""
    run = authoring.open_run(
        published_quiz(), admin_id=ADMIN_ID, results={SCOREBOARD_VISIBILITY: "live"}
    )
    brand(run.quiz)
    shows_quiz_branding(text(FormClient().get(f"/q/kviz/r/{run.id}/scoreboard")))


def test_test_link_shows_the_quiz_branding():
    """AC-94."""
    quiz = published_quiz()
    brand(quiz)
    link = run_links.create(
        quiz, authoring.latest_published(quiz), expires_at=None, admin_id=ADMIN_ID
    )
    shows_quiz_branding(text(FormClient().get(f"/t/{link.token}")))


def test_preview_shows_the_quiz_branding(logged_in):
    """AC-94."""
    quiz = published_quiz()
    brand(quiz)
    shows_quiz_branding(text(logged_in.get(f"/admin/quizzes/{quiz.id}/preview")))


def test_landing_and_about_show_the_global_branding(client):
    """AC-94, AC-96."""
    brand(None)
    landing = text(client.get("/"))
    shows_quiz_branding(landing)
    assert "Hurá do kvízu" in landing
    shows_quiz_branding(text(client.get("/about")))


def test_admin_pages_use_the_global_branding(logged_in):
    """AC-94."""
    brand(None)
    html = text(logged_in.get("/admin/settings"))
    assert "Moje škola</a>" in html and f"/media/{LOGO}" in html


BAR = r'<img class="site-logo" src="/assets/logo-mint-bar\.svg" alt=""'


def test_logo_next_to_the_name_has_an_empty_alt(client):
    """AC-94."""
    assert re.search(BAR, text(client.get("/")))


def test_defaults_without_branding(client):
    """AC-94."""
    html = text(client.get("/"))
    assert "Kvízotron</a>" in html and "/assets/logo-mint-bar.svg" in html
    assert 'data-palette="blue_teal"' in html and ':root[data-palette="custom"]' not in html


def test_landing_hero_is_a_picture_with_a_dark_twin(client):
    """AC-148."""
    html = text(client.get("/"))
    assert re.search(BAR, html)
    assert "hero-logo-plate" not in html
    assert re.search(
        r'<picture>\s*<source media="\(prefers-color-scheme: dark\)" '
        r'srcset="/assets/logo-mint-hero-dark\.svg">\s*'
        r'<img class="about-logo about-logo-centered about-logo-builtin" '
        r'src="/assets/logo-mint-hero-light\.svg"',
        html,
    )


def test_an_uploaded_large_logo_has_no_plate_and_no_dark_source():
    branding.set_hero_logo(None, png_bytes(), admin_id=ADMIN_ID)
    html = text(FormClient().get("/"))
    assert re.search(BAR, html)
    assert 'class="about-logo' in html and "/media/" in html
    assert "hero-logo-plate" not in html and "<source" not in html


def test_the_built_in_large_logo_has_no_plate(client):
    assert "hero-logo-plate" not in text(client.get("/"))


@pytest.mark.parametrize("path", ["/", "/about"])
def test_hiding_the_large_logo_hides_it_on_both_pages(path):
    """AC-149."""
    settings.set_global(settings.SHOW_HERO_LOGO, "off", admin_id=ADMIN_ID)
    html = text(FormClient().get(path))
    assert 'class="about-logo' not in html and "hero-logo-plate" not in html
    assert re.search(BAR, html)


def quiz_page():
    authoring.open_run(quiz := published_quiz(), admin_id=ADMIN_ID)
    return quiz


def test_a_quiz_page_shows_no_large_logo_by_default():
    """AC-150."""
    quiz_page()
    assert 'class="about-logo' not in text(FormClient().get("/q/kviz"))


def test_a_quiz_page_shows_the_quizs_own_large_logo_without_a_plate():
    """AC-150."""
    branding.set_hero_logo(quiz_page(), png_bytes(), admin_id=ADMIN_ID)
    html = text(FormClient().get("/q/kviz"))
    assert 'class="about-logo' in html and "/media/" in html and "hero-logo-plate" not in html


def test_a_global_large_logo_does_not_appear_on_a_quiz_page():
    """AC-150."""
    quiz_page()
    branding.set_hero_logo(None, png_bytes(), admin_id=ADMIN_ID)
    assert 'class="about-logo' not in text(FormClient().get("/q/kviz"))


def test_about_page_shows_the_resolved_hero_logo(client):
    html = text(client.get("/about"))
    assert "hero-logo-plate" not in html
    assert "/assets/logo-mint-about-light.svg" in html
    assert "/assets/logo-mint-about-dark.svg" in html
    assert "about-logo-full" in html and "hero-light" not in html


def test_bar_and_hero_logo_follow_a_custom_palette():
    """AC-148."""
    branding.set_colours(None, BrandColours("#ff6a00", "#336699"), admin_id=ADMIN_ID)
    settings.set_global(COLOR_PALETTE, CUSTOM_PALETTE, admin_id=ADMIN_ID)
    html = text(FormClient().get("/"))
    assert "/assets/logo-amber-bar.svg" in html and "/assets/logo-amber-hero-light.svg" in html


def test_the_kvizotron_line_is_on_every_public_page_with_a_link_to_about(client):
    """AC-97."""
    brand(None, footer="Naše patička")
    for path in ("/", "/about", "/privacy", "/how-it-works"):
        html = text(client.get(f"{path}?lang=en"))
        footer = html.split('<footer class="site-footer">')[1].split("</footer>")[0]
        assert "Naše patička" in footer
        assert re.search(r'<a href="/about[^"]*">Runs on Kvízotron [^<]*</a>', footer)


def test_the_kvizotron_line_stays_with_an_empty_footer(client):
    """AC-97."""
    html = text(client.get("/?lang=en"))
    assert '<footer class="site-footer">' in html
    assert "Runs on Kvízotron" in html


def test_markup_in_name_and_footer_is_escaped_and_never_in_the_style():
    """AC-94, AC-96."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    brand(run.quiz, name="</style><script>alert(1)</script>", footer="<script>x</script>")
    html = text(FormClient().get("/q/kviz"))
    assert "<script>alert(1)" not in html and "<script>x</script>" not in html
    assert "&lt;script&gt;alert(1)" in html
    style = re.search(r"<style[^>]*>(.*?)</style>", html, re.S)
    assert style and "script" not in style.group(1) and "alert" not in style.group(1)
    assert html.count("<style") == 1


def test_a_global_custom_palette_gives_the_style_block(client):
    """AC-96."""
    brand(None, logo=False)
    html = text(client.get("/"))
    assert 'data-palette="custom"' in html
    block = re.search(r"<style[^>]*>(.*?)</style>", html, re.S).group(1)
    assert block.count(':root[data-palette="custom"]') == 2
    assert "prefers-color-scheme: dark" in block
    assert all(f"--kvz-{name}:" in block for name in ("main", "bar", "surface"))


def test_the_csp_allows_only_the_nonced_style_block(client):
    """AC-96."""
    plain = client.get("/")["Content-Security-Policy"]
    assert "nonce-" not in plain and "unsafe-inline" not in plain
    brand(None, logo=False)
    response = client.get("/")
    nonce = re.search(r"<style nonce=\"([^\"]+)\"", text(response)).group(1)
    assert f"'nonce-{nonce}'" in response["Content-Security-Policy"]


def test_the_quiz_page_shows_the_built_in_motto_without_branding():
    """AC-94."""
    authoring.open_run(published_quiz(locales=("cs", "en")), admin_id=ADMIN_ID)
    html = text(FormClient().get("/q/kviz?lang=en"))
    assert '<p class="motto">Turn on your brain. Start Kvízotron.</p>' in html


def test_the_kvizotron_line_is_on_the_quiz_page_and_the_play_page():
    """AC-97."""
    run = authoring.open_run(published_quiz(locales=("cs", "en")), admin_id=ADMIN_ID)
    client = FormClient()
    for html in (
        text(client.get("/q/kviz?lang=en")),
        text(client.post(f"/r/{run.id}/start", {"lang": "en"})),
    ):
        footer = html.split('<footer class="site-footer">')[1].split("</footer>")[0]
        assert "Runs on Kvízotron" in footer


def test_the_page_of_a_quiz_that_is_not_running_shows_the_quiz_branding():
    quiz = published_quiz()
    brand(quiz)
    response = FormClient().get("/q/kviz")
    assert response.status_code == 200
    shows_quiz_branding(text(response))


def footer_of(html):
    return html.split('<footer class="site-footer">')[1].split("</footer>")[0]


def lines_of(footer):
    return re.findall(r'<p class="site-footer-line[^"]*">(.*?)</p>', footer, re.S)


def test_footer_has_two_lines_with_the_parts_in_order(client):
    """AC-97, AC-98: the organisation's line, then the application's line."""
    from importlib.metadata import version

    from django.utils import timezone

    brand(None, footer="Naše patička", logo=False, custom=False)
    branding.set_contact_email(None, "info@example.org", admin_id=ADMIN_ID)
    footer = footer_of(text(client.get("/?lang=en")))
    organisation, application = lines_of(footer)
    assert organisation.index("Naše patička") < organisation.index('href="mailto:info@example.org"')
    positions = [
        application.index(part)
        for part in (
            "GPL-3.0-or-later",
            'alt="Python"',
            'alt="Django"',
            'alt="HTMX"',
            f"Runs on Kvízotron {version('kvizotron')}",
            str(timezone.localtime().year),
        )
    ]
    assert positions == sorted(positions)
    assert re.search(r"\s·\s", organisation) and re.search(r"\s·\s", application)
    assert re.search(r'<a href="/about[^"]*">GPL-3.0-or-later</a>', application)
    for name in ("python", "django", "htmx"):
        url = re.search(rf'src="([^"]*badge-{name}\.svg)"', application).group(1)
        assert client.get(url).status_code == 200


def test_footer_parts_break_only_between_parts(client):
    """A part moves to the next line whole; only a part wider than the screen breaks inside."""
    brand(None, footer="Naše patička", logo=False, custom=False)
    branding.set_contact_email(None, "info@example.org", admin_id=ADMIN_ID)
    footer = footer_of(text(client.get("/?lang=en")))
    for line in lines_of(footer):
        parts = [part.strip() for part in re.split(r"\s·\s", line) if part.strip()]
        assert all(re.match(r'<span class="site-footer-part[ "]', part) for part in parts), parts
    css = (THEME / "theme.css").read_text()
    rule = re.search(r"\.site-footer-part \{([^}]*)\}", css).group(1)
    assert "display: inline-block" in rule and "max-width: 100%" in rule


def test_footer_omits_missing_text_and_email(client):
    """AC-98: without footer text and e-mail the organisation's line is left out."""
    footer = footer_of(text(client.get("/?lang=en")))
    assert "mailto:" not in footer
    lines = lines_of(footer)
    assert len(lines) == 1 and "GPL-3.0-or-later" in lines[0]
    assert not lines[0].strip().startswith("·")


def test_footer_with_only_an_email_has_no_leading_separator(client):
    branding.set_contact_email(None, "info@example.org", admin_id=ADMIN_ID)
    organisation, _application = lines_of(footer_of(text(client.get("/?lang=en"))))
    assert organisation.strip().startswith(
        '<span class="site-footer-part">Need help? Write to <a href="mailto:'
    )


def test_admin_pages_have_the_footer(logged_in):
    brand(None, footer="Naše patička", logo=False, custom=False)
    for path in ("/admin/quizzes", "/admin/settings", "/admin/users"):
        footer = footer_of(text(logged_in.get(path)))
        assert "Naše patička" in footer and "GPL-3.0-or-later" in footer


def test_the_logo_link_keeps_the_language(client, logged_in):
    assert 'class="site-name" href="/?lang=uk"' in text(client.get("/about?lang=uk"))
    logged_in.get("/admin/quizzes?lang=en")
    assert 'class="site-name" href="/?lang=en"' in text(logged_in.get("/admin/quizzes"))


def test_quiz_page_footer_falls_back_to_the_creator_email_and_landing_does_not(client):
    """AC-99."""
    from app.kernel.models import AdminUser

    admin = AdminUser.objects.create_admin("carol", "x-y-z-long-password-1")
    admin.email = "carol@example.org"
    admin.save()
    quiz = published_quiz()
    quiz.created_by = str(admin.pk)
    quiz.save()
    authoring.open_run(quiz, admin_id=ADMIN_ID)
    assert "mailto:carol@example.org" in footer_of(text(FormClient().get("/q/kviz")))
    assert "mailto:" not in footer_of(text(client.get("/")))


def test_footer_markup_is_escaped(client):
    brand(None, footer="<script>x</script>", logo=False, custom=False)
    assert "<script>x</script>" not in footer_of(text(client.get("/")))


def test_a_motto_of_two_sentences_is_set_as_two_lines(client):
    branding.set_texts(None, "motto", {"cs": "Zapni mozek. Spusť <Kvízotron>."}, admin_id=ADMIN_ID)
    html = text(client.get("/"))
    assert '<span class="motto-first">Zapni mozek.</span>' in html
    assert '<span class="motto-rest">Spusť &lt;Kvízotron&gt;.</span>' in html


def test_a_motto_of_one_sentence_stays_one_line(client):
    branding.set_texts(None, "motto", {"cs": "Hurá do kvízu"}, admin_id=ADMIN_ID)
    html = text(client.get("/"))
    assert "<h1>Hurá do kvízu</h1>" in html and "motto-first" not in html


def test_the_contact_says_what_it_is_for(client):
    """AC-98: the footer and the About page say that the address is for help."""
    branding.set_contact_email(None, "info@example.org", admin_id=ADMIN_ID)
    assert "Need help? Write to <a" in footer_of(text(client.get("/?lang=en")))
    about = text(client.get("/about?lang=en"))
    assert "Need help with a quiz or with your data? Write to" in about
    assert text(client.get("/about?lang=cs")).count("Potřebuješ pomoct") == 2


def test_a_quiz_and_its_result_show_the_contact_of_that_quiz_once_in_the_footer():
    """AC-98: the contact of a quiz is in the footer only, not again in the card or the result."""
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    branding.set_contact_email(run.quiz, "kviz@example.org", admin_id=ADMIN_ID)
    pages = [text(FormClient().get("/q/kviz"))]
    client, attempt, _html = played(run)
    pages.append(text(client.get(f"/v/{tokens.issue_result(attempt.id)}")))
    for html in pages:
        assert html.count("mailto:kviz@example.org") == 1
        assert "<small>Potřebuješ pomoct" not in html
        assert "mailto:kviz@example.org" in footer_of(html)


def test_a_quiz_without_a_contact_has_no_help_line():
    run = authoring.open_run(published_quiz(), admin_id=ADMIN_ID)
    assert "Piš na" not in text(FormClient().get("/q/kviz")).split("<footer")[0]
    client, attempt, _html = played(run)
    result = text(client.get(f"/v/{tokens.issue_result(attempt.id)}"))
    assert "Piš na" not in result.split("<footer")[0]
