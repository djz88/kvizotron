from app.contracts import (
    ARCHIVED_RESULTS,
    OFFICIAL_ATTEMPT,
    REVISION_MODE,
    SCOREBOARD_LIVE_NAMES,
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
        "group": "scoreboard",
        "level": "basic" if key == SCOREBOARD_VISIBILITY else "advanced",
    }


MANIFEST = {
    "id": "results.local",
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
            ["best", "first"],
            "best",
            _("Attempt that counts"),
            {"best": _("Best valid attempt"), "first": _("First valid attempt")},
            _("Of equal scores of one participant the earlier counts."),
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
            ["separate", "latest"],
            "separate",
            _("Runs with more revisions"),
            {"separate": _("One table per revision"), "latest": _("Only the latest revision")},
            _("Revisions with equal maximum points can be merged on the run page."),
        ),
        _setting(
            ARCHIVED_RESULTS,
            ["off", "on"],
            "off",
            _("Public results of an archived run"),
            {"off": _("Not public"), "on": _("Public")},
        ),
    ],
}
