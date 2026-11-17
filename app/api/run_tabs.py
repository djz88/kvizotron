"""The tabs of a run's admin page: one page per part, its address after `/` (ADR-0068)."""

from dataclasses import dataclass
from typing import Any

from django.utils.functional import Promise
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from app.domain import retention, rewards
from app.domain.models import QuizRun, RewardRule


@dataclass(frozen=True)
class Tab:
    key: str
    url_name: str
    label: str | Promise
    more: bool  # under "More" in the bar, as in the quiz header


TABS: tuple[Tab, ...] = (
    Tab("overview", "admin_run", gettext_lazy("Overview"), more=False),
    Tab("attempts", "admin_run_attempts", gettext_lazy("Attempts"), more=False),
    Tab("scoreboard", "admin_run_scoreboard", gettext_lazy("Scoreboard"), more=False),
    Tab("statistics", "admin_run_statistics", gettext_lazy("Statistics"), more=False),
    Tab("rewards", "admin_run_rewards", gettext_lazy("Rewards"), more=True),
    Tab("draw", "admin_run_draw", gettext_lazy("Draw"), more=True),
    Tab("export", "admin_run_export", gettext_lazy("Export"), more=True),
    Tab("settings", "admin_run_settings", gettext_lazy("Settings"), more=True),
)


def has_draw(run: QuizRun) -> bool:
    return any(rule.kind == RewardRule.Kind.DRAW for rule in rewards.rules_of(run))


def settings_empty(run: QuizRun, *, basic: bool) -> bool:
    """Settings shows nothing in the Basic view: no access code and no data to delete."""
    return basic and not run.access_code_hash and not retention.deletable(run)


def shown(run: QuizRun, *, basic: bool, current: str | None = None) -> list[Tab]:
    """Draw only with a draw rule; Settings only when it has something to show. The current tab
    is always listed, so the bar can mark it."""
    hidden = set()
    if not has_draw(run):
        hidden.add("draw")
    if settings_empty(run, basic=basic):
        hidden.add("settings")
    hidden.discard(current)
    return [tab for tab in TABS if tab.key not in hidden]


def status_label(run: QuizRun) -> str:
    labels = {
        QuizRun.Status.SCHEDULED: _("Planned"),
        QuizRun.Status.OPEN: _("Running"),
        QuizRun.Status.CLOSED: _("Ended"),
        QuizRun.Status.ARCHIVED: _("Archived"),
    }
    return labels[QuizRun.Status(run.status)]


def header(run: QuizRun, tab: str, *, basic: bool) -> dict[str, Any]:
    """What `admin/_run_header.html` needs on every tab, also on pages outside `admin_runs`."""
    return {
        "run": run,
        "status_label": status_label(run),
        "run_tabs": shown(run, basic=basic, current=tab),
        "run_tab": tab,
    }
