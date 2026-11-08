"""What every page of one quiz shows above its content: status, next steps and tabs."""

from typing import Any

from app.api import rendering
from app.api.rendering import media_storage
from app.domain import clock, external_images, grading, quiz_state, requirements
from app.domain.models import Quiz


def quiz_title(quiz: Quiz) -> str:
    return quiz.title.get(quiz.default_locale) or quiz.slug


def image_check(quiz: Quiz) -> dict[str, Any]:
    """The stored results, so that a tab opened within the hour still warns."""
    addresses = external_images.addresses_of(quiz)
    storage = media_storage()
    status = storage.address_status(addresses) if storage and addresses else {}
    checked = [item.checked_at for item in status.values()]
    return {
        "addresses": addresses,
        "failed": [address for address, item in status.items() if not item.ok],
        "checked_at": clock.shown(max(checked)) if checked else None,
    }


def workspace(quiz: Quiz, tab: str, run_error: str | None = None) -> dict[str, Any]:
    """`tab` is the last part of its address: `edit`, `runs`, `grading` and so on."""
    return {
        "quiz": quiz,
        "title": quiz_title(quiz),
        "tab": tab,
        "can_import": rendering.can_import(),
        "run_error": run_error,
        "state": quiz_state.of(quiz),
        "image_check": image_check(quiz),
        "requirements": requirements.unmet(quiz),
        "waiting": grading.waiting_in_quiz(quiz),
    }
