from app.contracts import REWARD_SOURCE, REWARD_THRESHOLDS, WINNER_CONTACT


def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


_REASON = "Applies to the whole run, not to one question."
_SCOPES = ["global", "quiz"]


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
        "group": "rewards",
        "level": "advanced",
    }


MANIFEST = {
    "id": "rewards.threshold",
    "name": _("Rewards"),
    "description": _("Rewards for reaching a threshold."),
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.rewards.apps.RewardsConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["reward"],
    "requires": [],
    "activation_scope": ["global"],
    "settings": [
        _setting(
            REWARD_SOURCE,
            ["none", "previous_run", "quiz"],
            "none",
            _("Rewards of a new run"),
            {
                "none": _("None"),
                "previous_run": _("From the previous run"),
                "quiz": _("From the quiz template"),
            },
            _("Only fills a new run; the run then keeps its own rewards."),
        ),
        _setting(
            REWARD_THRESHOLDS,
            ["highest", "all"],
            "highest",
            _("Several thresholds"),
            {"highest": _("Only the highest reached"), "all": _("All reached")},
            _("Which threshold rewards one participant gets when several are reached."),
        ),
        _setting(
            WINNER_CONTACT,
            ["warn", "require_email", "silent"],
            "warn",
            _("Contacting winners"),
            {
                "warn": _("Warn when e-mail is not collected"),
                "require_email": _("A draw requires an e-mail"),
                "silent": _("No warning"),
            },
            _("The system sends no e-mails; winners are contacted by the admin."),
        ),
    ],
}
