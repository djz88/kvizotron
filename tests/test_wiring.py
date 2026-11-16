"""What was built is connected: modules, pages, assets, settings and addresses.

These tests read the real code, and each names what is missing. `make wiring` runs just them; the
skill `kvizotron-check-applied` says where they fit.
"""

import re
import tomllib
from functools import cache
from pathlib import Path

import pytest
from django.conf import settings as django_settings
from django.template import engines
from django.urls import URLPattern, URLResolver, get_resolver, resolve
from django.urls.exceptions import Resolver404
from jinja2 import meta

from app.api import admin_urls
from app.api.public import ASSETS, SERVED_ASSETS
from app.domain import settings
from app.kernel import registry
from app.kernel.discovery import installed_modules
from tools.messages import ROOTS

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
THEME = APP / "plugins" / "theme_default" / "assets"
BUNDLED_SCRIPTS = {"htmx.min.js", "sortable.js"}

# Ports that are not looked up in the registry: Django and the kernel load these.
LOADED_AT_START = {"auth", "persistence"}
NO_SHARED_SUITE_YET: set[str] = set()
# Names an element without any rule in the stylesheets. The list only shrinks: a new class needs a
# rule, because a page with a lost stylesheet still passes every test that reads its HTML.
NOT_STYLED = {
    "add-menu",
    "draw-row",
    "grading-attempts",
    "mode-bar",
    "own-answer",
    "requirement",
    "result",
    "result-link",
    "result-slot",
    "reveal-theirs",
    "row-actions",
    "sortable-note",
    "walkthrough-question",
    "watch-changes",
}
OPEN_WITHOUT_LOGIN = {"admin_login", "admin_logout"}
UNIT = "00000000-0000-7000-8000-000000000001"


def package_of(module) -> Path:
    return ROOT / Path(module.app.split(".apps.")[0].replace(".", "/"))


@cache
def templates() -> dict[str, str]:
    env = next(engine.env for engine in engines.all() if hasattr(engine, "env"))
    return {name: env.loader.get_source(env, name)[0] for name in env.list_templates()}


@cache
def jinja_env():
    return next(engine.env for engine in engines.all() if hasattr(engine, "env"))


@cache
def python_sources() -> dict[Path, str]:
    return {path: path.read_text() for path in APP.rglob("*.py")}


@cache
def own_scripts() -> str:
    return "\n".join(
        path.read_text() for path in ASSETS.glob("*.js") if path.name not in BUNDLED_SCRIPTS
    )


def all_templates() -> str:
    return "\n".join(templates().values())


def route_names(resolver, prefix="") -> set[str]:
    names = set()
    for entry in resolver.url_patterns:
        if isinstance(entry, URLResolver):
            inner = f"{prefix}{entry.namespace}:" if entry.namespace else prefix
            names |= route_names(entry, inner)
        elif entry.name:
            names.add(prefix + entry.name)
    return names


def entry_points() -> dict[str, str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    return project["entry-points"]["kvizotron.modules"]


def test_each_manifest_is_registered_and_each_entry_has_a_manifest():
    found = {
        ".".join(path.relative_to(ROOT).with_suffix("").parts) + ":MANIFEST"
        for folder in ("plugins", "providers")
        for path in (APP / folder).rglob("manifest.py")
    }
    assert found == set(entry_points().values())


def test_the_installed_modules_match_the_project_file():
    """When this fails after adding a module, `make setup` refreshes the installed entry points."""
    assert {module.id for module in installed_modules()} == set(entry_points())


def test_each_module_is_an_installed_app():
    missing = {m.id for m in installed_modules()} - {
        module.id for module in django_settings.KVZ_MODULES if module.app
    }
    assert not missing
    assert not [m.app for m in installed_modules() if m.app not in django_settings.INSTALLED_APPS]


def test_each_module_registers_what_it_provides():
    owned = {(capability, owner) for (capability, _key), (_i, owner) in registry._ports.items()}
    missing = [
        f"{module.id}: {port}"
        for module in installed_modules()
        for port in module.provides
        if port not in LOADED_AT_START and (port, module.id) not in owned
    ]
    assert not missing


def test_a_module_with_texts_has_a_catalogue_that_gets_built():
    wrong = []
    roots = {root.resolve() for root in ROOTS}
    for module in installed_modules():
        package = package_of(module)
        code = any(re.search(r"gettext|\b_\(", p.read_text()) for p in package.rglob("*.py"))
        pages = any("_(" in p.read_text() for p in package.rglob("*.html"))
        if (code or pages) and (package not in roots or not (package / "locale").is_dir()):
            wrong.append(module.id)
    assert not wrong


def test_each_module_is_named_by_a_shared_suite():
    suites = "\n".join(p.read_text() for p in (ROOT / "tests" / "contracts").glob("test_*.py"))
    named_by_port = {"csv_io": "ExporterProvider", "media_local": "MediaStorageSuite"}
    missing = {
        package_of(module).name
        for module in installed_modules()
        if named_by_port.get(package_of(module).name, package_of(module).name) not in suites
    }
    assert missing == NO_SHARED_SUITE_YET


def test_each_module_has_its_document():
    architecture = ROOT / "docs" / "_architecture"
    question_types = (architecture / "plugins" / "question-types.md").read_text()
    missing = []
    for module in installed_modules():
        package = package_of(module)
        if package.parent.name == "questions":
            if f"`{package.name}`" not in question_types:
                missing.append(module.id)
            continue
        folder = "providers" if module.kind == "provider" else "plugins"
        if not (architecture / folder / f"{package.name.replace('_', '-')}.md").is_file():
            missing.append(module.id)
    assert not missing


def test_each_template_a_template_uses_exists():
    known = set(templates())
    env = jinja_env()
    missing = {
        f"{name}: {used}"
        for name, source in templates().items()
        for used in meta.find_referenced_templates(env.parse(source))
        if used and used not in known
    }
    assert len(known) > 50
    assert not missing


def test_each_template_the_code_names_exists():
    known = set(templates())
    missing = {
        f"{path.relative_to(ROOT)}: {name}"
        for path, source in python_sources().items()
        for name in re.findall(r"""["']([\w/.-]+\.html)["']""", source)
        if name not in known
    }
    assert not missing


def test_each_route_a_template_names_exists():
    known = route_names(get_resolver())
    used = {
        (name, route)
        for name, source in templates().items()
        for route in re.findall(r"""\burl\(\s*["']([\w:.-]+)["']""", source)
    }
    assert len(used) > 50
    assert not {pair for pair in used if pair[1] not in known}


def test_each_fixed_address_in_a_template_leads_somewhere():
    attribute = r"""(?:href|action|src|hx-(?:get|post|put|delete))=["'](/[^"'{]*)["']"""
    broken = set()
    for name, source in templates().items():
        for address in re.findall(attribute, source):
            try:
                resolve(address.split("?")[0])
            except Resolver404:
                broken.add(f"{name}: {address}")
    assert not broken


def test_each_asset_file_is_served_and_each_served_asset_exists():
    assert {path.name for path in ASSETS.iterdir() if path.is_file()} == set(SERVED_ASSETS)


def test_each_named_asset_is_served_and_each_served_asset_is_used():
    sources = all_templates() + "\n".join(python_sources().values())
    named = set(re.findall(r"/assets/([\w-]+\.\w+)", sources))
    named |= set(re.findall(r"""["']([\w-]+\.js)["']""", sources))
    assert not named - set(SERVED_ASSETS)
    unused = {
        name
        for name in SERVED_ASSETS
        # The flags are built from the language code, the logos from the family and the kind.
        if sources.count(name) < 2 and not name.startswith(("flag-", "logo-"))
    }
    assert not unused


def test_each_hook_a_script_looks_for_is_on_a_page():
    scripts = own_scripts()
    pages = all_templates() + "\n".join(python_sources().values())
    camel = re.compile(r"[A-Z]")
    set_by_script = {
        camel.sub(lambda m: "-" + m[0].lower(), name)
        for name in re.findall(r"dataset\.(\w+)\s*=[^=]", scripts)
    }
    read = set(re.findall(r"\[data-([\w-]+)", scripts)) | {
        camel.sub(lambda m: "-" + m[0].lower(), name)
        for name in re.findall(r"dataset\.(\w+)", scripts)
    }
    assert len(read) > 5
    assert not {hook for hook in read - set_by_script if f"data-{hook}" not in pages}
    ids = re.findall(r"""getElementById\(["']([\w-]+)|querySelector\(["']#([\w-]+)""", scripts)
    assert not {a or b for a, b in ids if f'id="{a or b}"' not in pages}


def test_each_element_htmx_is_told_to_change_exists():
    pages = all_templates()
    # An address ending in a value from the template is built when the page is drawn.
    pattern = r"""hx-(?:target|select|swap-oob|include)=["']#([\w-]+)(?!\{\{)["']"""
    missing = {
        f"{name}: {target}"
        for name, source in templates().items()
        for target in re.findall(pattern, source)
        if f'id="{target}"' not in pages
    }
    assert not missing


def test_each_class_on_a_page_has_a_rule_or_is_listed():
    rules = (THEME / "theme.css").read_text() + (THEME / "pico.min.css").read_text()
    defined = set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", rules))
    used = set()
    for source in templates().values():
        for value in re.findall(r"""class=["']([^"']*)["']""", source):
            plain = re.sub(r"\{[{%].*?[%}]\}", " ", value)
            used |= {name for name in plain.split() if re.fullmatch(r"[a-zA-Z][\w-]*\w", name)}
    assert len(used) > 50
    assert not used - defined - NOT_STYLED
    assert not NOT_STYLED & defined, "it has a rule now, remove it from NOT_STYLED"
    assert not NOT_STYLED - used, "no page uses it now, remove it from NOT_STYLED"


def test_each_class_a_script_sets_has_a_rule():
    rules = (THEME / "theme.css").read_text() + (THEME / "pico.min.css").read_text()
    defined = set(re.findall(r"\.(-?[_a-zA-Z][\w-]*)", rules))
    named = set(re.findall(r"""classList\.(?:add|toggle|remove)\(["']([\w-]+)""", own_scripts()))
    assert not named - defined


def test_each_setting_is_read_somewhere():
    source_of_settings = APP / "domain" / "settings.py"
    own = python_sources()[source_of_settings]
    start = own.index("CATALOGUE = {")
    outside_catalogue = own[:start] + own[own.index("\n}\n", start) :]
    others = "\n".join(
        text
        for path, text in python_sources().items()
        if path != source_of_settings and path.name != "manifest.py"
    )
    unread = []
    for key in settings.CATALOGUE:
        constants = [n for n, v in vars(settings).items() if n.isupper() and v == key]
        reads = len(re.findall(rf"\b{key}\b", others))
        for constant in constants:
            reads += len(re.findall(rf"\b{constant}\b", others))
            uses = re.findall(rf"\b{constant}\b(?! = )", outside_catalogue)
            reads += len(uses)
        if not reads:
            unread.append(key)
    assert not unread


def test_each_question_setting_of_a_type_exists_at_that_level():
    for (capability, key), (plugin, _owner) in registry._ports.items():
        if capability == "question_type":
            for name in plugin.question_settings():
                assert "question" in settings.CATALOGUE[name].scopes, (key, name)


def test_each_event_is_documented():
    sources = "\n".join(python_sources().values())
    emitted = set(re.findall(r"""events\.emit\(\s*["']([\w.]+)""", sources))
    docs = "\n".join(
        path.read_text()
        for path in (ROOT / "docs").rglob("*.md")
        if "superpowers" not in path.parts
    )
    assert emitted
    assert not {event for event in emitted if event not in docs}


def admin_routes() -> list[tuple[str, str]]:
    routes = []
    for entry in admin_urls.urlpatterns:
        assert isinstance(entry, URLPattern)
        filled = re.sub(r"<uuid:\w+>", UNIT, str(entry.pattern))
        filled = re.sub(r"<(?:str|slug):\w+>", "x", filled)
        filled = re.sub(r"<int:\w+>", "1", filled)
        assert "<" not in filled, entry.pattern
        routes.append((entry.name, f"/admin/{filled}"))
    return routes


@pytest.mark.django_db
@pytest.mark.parametrize("name, address", admin_routes(), ids=lambda value: value)
@pytest.mark.parametrize("method", ["get", "post"])
def test_each_admin_route_needs_a_login(client, name, address, method):
    if name in OPEN_WITHOUT_LOGIN:
        pytest.skip("this route is how an admin gets in and out")
    response = getattr(client, method)(address)
    assert response.status_code == 302, response.status_code
    assert response["Location"].startswith("/admin/login")
