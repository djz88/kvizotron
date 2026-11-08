from app.contracts import LOCAL_RESUME


def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "flow.basic",
    "kind": "plugin",
    "version": "1.0.0",
    "app": "app.plugins.quiz_flow.apps.QuizFlowConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["quiz_flow"],
    "requires": [],
    "activation_scope": ["global"],
    "settings": [
        {
            "key": LOCAL_RESUME,
            "group": "playing",
            "choices": ["on", "off"],
            "default": "on",
            "scopes": ["global", "quiz"],
            "scope_reason": "Applies to the whole attempt, not to one question.",
            "label": _("Resume in this browser"),
            "value_labels": {
                "on": _("Keep unsent answers on this device"),
                "off": _("Do not keep unsent answers"),
            },
            "help": _(
                "Answers stay on this device until the attempt ends, at most 24 hours; "
                "a shared device can show them to the next person."
            ),
        }
    ],
}
