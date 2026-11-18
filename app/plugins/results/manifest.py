from app.contracts import (
    ARCHIVED_RESULTS,
    OFFICIAL_ATTEMPT,
    PASS_MARK,
    REVISION_MODE,
    SCOREBOARD_LIVE_NAMES,
    SCOREBOARD_RUNS,
    SCOREBOARD_SECOND_SORT,
    SCOREBOARD_SHOW_DURATION,
    SCOREBOARD_SHOW_PERCENT,
    SCOREBOARD_SHOW_SCORE,
    SCOREBOARD_SHOW_TIME,
    SCOREBOARD_UNNAMED,
    SCOREBOARD_VISIBILITY,
    TIE_BREAK_POLICY,
)


def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


_REASON = "Applies to the whole run, not to one question."
_SCOPES = ["global", "quiz"]
_SHOW = {"on": _("Show"), "off": _("Hide")}
_NEEDS_TIMES = _("Needs the data profile that keeps times.")


GROUPS = {PASS_MARK: "playing"}  # the rest, revision mode included, shape the scoreboard


def _setting(key, choices, default, label, value_labels, help_text=""):
    return {
        "key": key,
        "choices": choices,
        "default": default,
        "scopes": _SCOPES,
        "scope_reason": _REASON,
        "label": label,
        "value_labels": value_labels,
        "help": help_text,
        "group": GROUPS.get(key, "scoreboard"),
        "level": "basic" if key in (SCOREBOARD_VISIBILITY, PASS_MARK) else "advanced",
    }


MANIFEST = {
    "id": "results.local",
    "name": _("Results"),
    "description": _("Scoreboard, statistics and the comparison of runs."),
    "always_on": True,
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.results.apps.ResultsConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["result_view"],
    "requires": [],
    "activation_scope": ["global"],
    "settings": [
        _setting(
            SCOREBOARD_VISIBILITY,
            ["hidden", "live", "after_end"],
            "hidden",
            _("Public scoreboard"),
            {
                "hidden": _("Hidden"),
                "live": _("Visible during the run"),
                "after_end": _("Visible after the run ends"),
            },
            _(
                "A visible scoreboard remembers each browser with a cookie, "
                "so one person is one row."
            ),
        ),
        _setting(
            SCOREBOARD_LIVE_NAMES,
            ["shown", "anonymised"],
            "shown",
            _("Names during the run"),
            {"shown": _("Show nicknames"), "anonymised": _("Show anonymous labels")},
            _("After the run ends, nicknames are shown."),
        ),
        _setting(
            SCOREBOARD_UNNAMED,
            ["anonymous", "unlisted"],
            "anonymous",
            _("Participant without a nickname"),
            {"anonymous": _("Show with the anonymous label"), "unlisted": _("Leave out")},
        ),
        _setting(
            OFFICIAL_ATTEMPT,
            ["best", "first", "last", "average"],
            "best",
            _("Attempt that counts"),
            {
                "best": _("Best valid attempt"),
                "first": _("First valid attempt"),
                "last": _("The last attempt"),
                "average": _("The average of the attempts"),
            },
            _("Of equal scores of one participant the earlier counts."),
        ),
        _setting(
            PASS_MARK,
            [str(percent) for percent in range(101)],
            "0",
            _("Pass mark (%)"),
            {"0": _("No pass mark"), **{str(percent): str(percent) for percent in range(1, 101)}},
            _("Percent of the maximum score an attempt needs to pass."),
        ),
        _setting(SCOREBOARD_SHOW_SCORE, ["on", "off"], "on", _("Column: score"), _SHOW),
        _setting(SCOREBOARD_SHOW_PERCENT, ["on", "off"], "on", _("Column: percent"), _SHOW),
        _setting(SCOREBOARD_SHOW_TIME, ["on", "off"], "off", _("Column: submission time"), _SHOW),
        _setting(
            SCOREBOARD_SHOW_DURATION,
            ["on", "off"],
            "off",
            _("Column: duration"),
            _SHOW,
            _NEEDS_TIMES,
        ),
        _setting(
            SCOREBOARD_SECOND_SORT,
            ["submitted", "duration"],
            "submitted",
            _("Equal scores ordered by"),
            {"submitted": _("Earlier submission"), "duration": _("Shorter duration")},
            _NEEDS_TIMES,
        ),
        _setting(
            TIE_BREAK_POLICY,
            ["shared", "earlier", "random"],
            "shared",
            _("Remaining ties"),
            {
                "shared": _("Shared place"),
                "earlier": _("Earlier submission first"),
                "random": _("Random order, the same on every load"),
            },
        ),
        _setting(
            REVISION_MODE,
            ["percent", "separate", "latest"],
            "percent",
            _("Runs with more revisions"),
            {
                "percent": _("One table by percent"),
                "separate": _("One table per revision"),
                "latest": _("Only the latest revision"),
            },
            _(
                "One table ranks each attempt by the percent of its own revision's maximum. "
                "This choice also decides which attempt counts for rewards, draws and the "
                "pass mark."
            ),
        ),
        _setting(
            SCOREBOARD_RUNS,
            ["current", "all"],
            "current",
            _("Scoreboards on the quiz page"),
            {"current": _("Only the current run"), "all": _("All runs")},
            _("Each run shows its board only while its own visibility allows it."),
        )
        | {"scope_reason": _("Applies to the quiz page, not to one question.")},
        _setting(
            ARCHIVED_RESULTS,
            ["off", "on"],
            "off",
            _("Public results of an archived run"),
            {"off": _("Not public"), "on": _("Public")},
        ),
    ],
}
