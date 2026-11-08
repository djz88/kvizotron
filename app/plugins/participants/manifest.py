from app.contracts import (
    ASK_EMAIL,
    ASK_NAME,
    ASK_WHEN,
    DUPLICATE_NAMES,
    REPEAT_ATTEMPTS,
    UNFINISHED_ATTEMPT,
)


def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


_REASON = "Applies to the whole attempt, not to one question."
_SCOPES = ["global", "quiz"]
_ASK_LABELS = {
    "off": _("Do not ask"),
    "optional": _("Ask, may be left empty"),
    "required": _("Require"),
}

MANIFEST = {
    "id": "participants.basic",
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.participants.apps.ParticipantsConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["participant_policy"],
    "requires": [],
    "activation_scope": ["global"],
    "settings": [
        {
            "key": REPEAT_ATTEMPTS,
            "group": "participants",
            "level": "basic",
            "choices": ["allow", "forbid"],
            "default": "allow",
            "scopes": _SCOPES,
            "scope_reason": _REASON,
            "label": _("Attempt repeats"),
            "value_labels": {
                "allow": _("Anyone may play again"),
                "forbid": _("One attempt per browser"),
            },
            "help": _(
                "The browser is recognised by a cookie, so another browser or a cleared cookie "
                "starts a new attempt."
            ),
        },
        {
            "key": UNFINISHED_ATTEMPT,
            "group": "playing",
            "choices": ["continue", "used", "submitted"],
            "default": "continue",
            "scopes": _SCOPES,
            "scope_reason": _REASON,
            "label": _("An unfinished attempt"),
            "value_labels": {
                "continue": _("The participant continues it"),
                "used": _("It counts as the one attempt"),
                "submitted": _("It is closed and a new one may start"),
            },
            "help": _("Only matters when an attempt may not be repeated."),
        },
        {
            "key": ASK_NAME,
            "group": "participants",
            "level": "basic",
            "choices": ["off", "optional", "required"],
            "default": "off",
            "scopes": _SCOPES,
            "scope_reason": _REASON,
            "label": _("Nickname"),
            "value_labels": _ASK_LABELS,
            "help": _(
                "The administration of this run shows it, and so does the run's public "
                "scoreboard when the admin turns it on."
            ),
        },
        {
            "key": ASK_EMAIL,
            "group": "participants",
            "choices": ["off", "optional", "required"],
            "default": "off",
            "scopes": _SCOPES,
            "scope_reason": _REASON,
            "label": _("E-mail"),
            "value_labels": _ASK_LABELS,
            "help": _("An e-mail is shown only to logged-in administrators, never publicly."),
        },
        {
            "key": ASK_WHEN,
            "group": "participants",
            "choices": ["end", "start"],
            "default": "end",
            "scopes": _SCOPES,
            "scope_reason": _REASON,
            "label": _("When to ask"),
            "value_labels": {
                "end": _("After the last question"),
                "start": _("Before the first question"),
            },
            "help": _("Applies to the nickname and the e-mail."),
        },
        {
            "key": DUPLICATE_NAMES,
            "group": "participants",
            "choices": ["allow", "forbid"],
            "default": "allow",
            "scopes": _SCOPES,
            "scope_reason": _REASON,
            "label": _("Same nickname twice"),
            "value_labels": {"allow": _("Allow"), "forbid": _("Refuse within one run")},
            "help": _("Names differing only by case or inner spaces count as the same."),
        },
    ],
}
