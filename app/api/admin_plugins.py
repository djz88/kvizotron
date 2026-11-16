"""The Modules page (D4): what is installed, switching plugins, and where a value differs."""

from typing import Any

from django.conf import settings as django_settings
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from app.api.admin_auth import admin_required
from app.api.admin_workspace import quiz_title
from app.api.rendering import page
from app.domain import plugin_overview, settings
from app.kernel import lifecycle, registry
from app.kernel.manifest import Manifest

_TARGETS = {"run": "admin_run", "quiz": "admin_quiz_edit"}


def _manifest(module_id: str) -> Manifest:
    for manifest in django_settings.KVZ_MODULES:
        if manifest.id == module_id:
            return manifest
    raise Http404


def _name(manifest: Manifest) -> str:
    return _(manifest.name) if manifest.name else manifest.id  # noqa: INT001  # module's catalogue


def _reasons(manifest: Manifest, enabled: bool) -> list[lifecycle.Blocker]:
    """Why the module cannot leave the state it is in."""
    return lifecycle.blockers(manifest.id, not enabled)


def _row(manifest: Manifest) -> dict[str, Any]:
    enabled = registry.is_enabled(manifest.id)
    found = _reasons(manifest, enabled)
    is_plugin = manifest.kind == "plugin"
    reason = found[0].text if found else None
    if not is_plugin:
        reason = _("Changes on restart")
    return {
        "id": manifest.id,
        "name": _name(manifest),
        "kind": _("Plugin") if is_plugin else _("Provider"),
        "version": manifest.version,
        "enabled": enabled,
        "switchable": is_plugin and not found,
        "reason": reason,
    }


@admin_required
def plugins_page(request: HttpRequest) -> HttpResponse:
    modules = sorted(django_settings.KVZ_MODULES, key=lambda m: (m.kind != "plugin", _name(m)))
    context = {"rows": [_row(manifest) for manifest in modules]}
    return page(request, "admin/plugins.html", context, request.locale)  # type: ignore[attr-defined]


def _link(blocker: lifecycle.Blocker) -> str | None:
    if blocker.target is None:
        return None
    kind, target_id = blocker.target
    return reverse(_TARGETS[kind], args=[target_id])


def _providers_of(capability: str) -> list[Manifest]:
    return [m for m in django_settings.KVZ_MODULES if capability in m.provides]


def _difference(difference: plugin_overview.Difference, labels: Any) -> dict[str, str]:
    title = quiz_title(difference.quiz)
    if difference.question_no is None:
        where, href = title, reverse("admin_quiz_settings", args=[difference.quiz.id])
    else:
        where = _("%(title)s, question %(number)s") % {
            "title": title,
            "number": difference.question_no,
        }
        href = reverse("admin_question_edit", args=[difference.quiz.id, difference.question_id])
    return {"where": where, "href": href, "value": labels[difference.value]}


def _setting_rows(manifest: Manifest) -> list[dict[str, Any]]:
    rows = []
    for row in plugin_overview.overview(manifest):
        definition = settings.CATALOGUE[row.key]
        rows.append(
            {
                "label": definition.label,
                "global_value": definition.value_labels[row.global_value],
                "narrower": set(definition.scopes) & {"quiz", "question"},
                "differences": [_difference(d, definition.value_labels) for d in row.differences],
                "total": row.total,
                "cut": row.total > len(row.differences),
            }
        )
    return rows


def _detail(request: HttpRequest, manifest: Manifest, status: int = 200) -> HttpResponse:
    enabled = registry.is_enabled(manifest.id)
    found = _reasons(manifest, enabled)
    required = {m.id: m for c in manifest.requires for m in _providers_of(c)}
    dependents = [
        m
        for m in django_settings.KVZ_MODULES
        if m.id != manifest.id and set(m.requires) & set(manifest.provides)
    ]
    context = {
        "manifest": manifest,
        "name": _name(manifest),
        "description": _(manifest.description) if manifest.description else "",  # noqa: INT001
        "enabled": enabled,
        "switchable": manifest.kind == "plugin" and not found,
        "reasons": [{"text": b.text, "href": _link(b)} for b in found],
        "required": [(m.id, _name(m)) for m in required.values()],
        "dependents": [(m.id, _name(m)) for m in dependents],
        "settings": _setting_rows(manifest),
    }
    return page(request, "admin/plugin.html", context, request.locale, status=status)  # type: ignore[attr-defined]


@admin_required
def plugin_page(request: HttpRequest, module_id: str) -> HttpResponse:
    return _detail(request, _manifest(module_id))


@admin_required
@require_POST
def plugin_state(request: HttpRequest, module_id: str) -> HttpResponse:
    manifest = _manifest(module_id)
    wanted = {"on": True, "off": False}.get(request.POST.get("enabled", ""))
    if wanted is None:
        return HttpResponseBadRequest()
    try:
        lifecycle.set_enabled(module_id, wanted, actor_type="admin", actor_id=str(request.user.pk))
    except lifecycle.LifecycleError:
        return _detail(request, manifest, status=409)
    return redirect("admin_plugins")
