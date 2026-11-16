"""Which addresses a quiz's images actually load from, so only those get checked (ADR-0043)."""

from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts import IMAGE_MODE_EXTERNAL
from app.domain import authoring, banks, questions, selection, settings
from app.domain.models import Quiz

FETCHES_SECONDS = 25.0  # all address fetches of one save together (ADR-0043)


def _questions_of(quiz: Quiz) -> Iterable[Mapping[str, Any]]:
    yield from authoring.editable_questions(quiz)
    for row in authoring.editable_draws(quiz):
        yield from banks.pool(row, quiz.supported_locales)
    published = authoring.latest_published(quiz)
    if published is not None:
        yield from selection.all_questions(published.snapshot_json)


def addresses_of(quiz: Quiz) -> list[str]:
    """An image with no copy loads from its address whatever the mode."""
    found = set()
    for question in _questions_of(quiz):
        external = settings.image_mode(quiz, question) == IMAGE_MODE_EXTERNAL
        for image in questions.images_of(question["definition"]):
            source = image.get("source")
            if source and (external or not image.get("asset")):
                found.add(source)
    return sorted(found)
