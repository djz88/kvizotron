from app.contracts import (
    ALLOW_INTERNAL_IMAGE_ADDRESSES,
    EXTERNAL_IMAGE_MODE,
    IMAGE_MODE_COPY,
    IMAGE_MODE_EXTERNAL,
)


def _(text: str) -> str:
    """Marks a text for the module's catalogue; a manifest loads before Django."""
    return text


MANIFEST = {
    "id": "media.local",
    "name": _("Media storage"),
    "description": _("Images and photos stored on this server."),
    "kind": "provider",
    "version": "1.0.0",
    "app": "app.providers.media_local.apps.MediaLocalConfig",
    "api_compatibility": ">=1.0,<2.0",
    "provides": ["media_storage"],
    "settings": [
        {
            "key": EXTERNAL_IMAGE_MODE,
            "group": "technical",
            "choices": [IMAGE_MODE_COPY, IMAGE_MODE_EXTERNAL],
            "default": IMAGE_MODE_COPY,
            "label": _("Images from an address"),
            "value_labels": {
                IMAGE_MODE_COPY: _("Show a copy kept here"),
                IMAGE_MODE_EXTERNAL: _("Load them from their server"),
            },
            "help": _("A server that images load from sees the IP addresses of participants."),
        },
        {
            "key": ALLOW_INTERNAL_IMAGE_ADDRESSES,
            "group": "technical",
            "choices": ["off", "on"],
            "default": "off",
            "scopes": ["global"],
            "scope_reason": "It guards the server, not a quiz.",
            "label": _("Fetching images from the internal network"),
            "value_labels": {"off": _("Refuse"), "on": _("Allow")},
            "help": _(
                "Any admin can turn this on, so a stolen admin account could use it to reach "
                "the internal network."
            ),
        },
    ],
}
