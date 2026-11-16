"""Extracts translatable strings and compiles catalogues, with no system gettext (make messages).

Source strings are English, so there is no `en` catalogue.
"""

from datetime import UTC, datetime
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.extract import DEFAULT_KEYWORDS, extract_from_dir
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

REPO = Path(__file__).resolve().parents[1]
LOCALES = ("cs", "uk")
ROOTS = (
    REPO / "app" / "api",
    REPO / "app" / "domain",
    REPO / "app" / "kernel",
    REPO / "app" / "plugins" / "drawings",
    REPO / "app" / "plugins" / "questions" / "choice",
    REPO / "app" / "plugins" / "questions" / "image_answer",
    REPO / "app" / "plugins" / "questions" / "matching",
    REPO / "app" / "plugins" / "questions" / "number",
    REPO / "app" / "plugins" / "questions" / "text",
    REPO / "app" / "plugins" / "participants",
    REPO / "app" / "plugins" / "results",
    REPO / "app" / "plugins" / "rewards",
    REPO / "app" / "plugins" / "quiz_flow",
    REPO / "app" / "plugins" / "quiz_types",
    REPO / "app" / "plugins" / "scoring",
    REPO / "app" / "plugins" / "theme_default",
    REPO / "app" / "providers" / "auth_local",
    REPO / "app" / "providers" / "csv_io",
    REPO / "app" / "providers" / "media_local",
    REPO / "app" / "providers" / "persistence_sqlite",
    REPO / "app" / "providers" / "retention",
)
METHODS = [("**.py", "python"), ("**/jinja2/**.html", "jinja2")]
OPTIONS = {"**/jinja2/**.html": {"extensions": "jinja2.ext.i18n", "newstyle_gettext": "true"}}
# Babel stamps the header with the current time; a fixed date keeps the .mo bytes stable.
FIXED_DATE = datetime(2000, 1, 1, tzinfo=UTC)
KEYWORDS = {**DEFAULT_KEYWORDS, "gettext_lazy": None}


def extract(root: Path) -> Catalog:
    catalog = Catalog()
    found = extract_from_dir(root, METHODS, OPTIONS, keywords=KEYWORDS)
    for filename, lineno, message, comments, context in found:
        catalog.add(message, None, [(filename, lineno)], auto_comments=comments, context=context)
    return catalog


def build(root: Path, locale: str) -> None:
    directory = root / "locale" / locale / "LC_MESSAGES"
    directory.mkdir(parents=True, exist_ok=True)
    po_path = directory / "django.po"
    if po_path.exists():
        with po_path.open("rb") as file:
            catalog = read_po(file, locale=locale)
    else:
        catalog = Catalog(locale=locale, project="Kvízotron")
    catalog.update(extract(root), no_fuzzy_matching=True)
    catalog.creation_date = FIXED_DATE
    catalog.revision_date = FIXED_DATE
    with po_path.open("wb") as file:
        write_po(
            file, catalog, width=0, omit_header=True, ignore_obsolete=True, include_lineno=False
        )
    with (directory / "django.mo").open("wb") as file:
        write_mo(file, catalog)


def main() -> None:
    for root in ROOTS:
        for locale in LOCALES:
            build(root, locale)


if __name__ == "__main__":
    main()
