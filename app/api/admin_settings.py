"""Global settings. A quiz can override them on its edit page."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from app.api import admin_view
from app.api.admin_auth import admin_required
from app.api.admin_forms import GlobalSettingsForm
from app.api.rendering import page
from app.domain import settings


@admin_required
def settings_page(request: HttpRequest) -> HttpResponse:
    form = GlobalSettingsForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        for key, value in form.cleaned_data.items():
            if value and value != settings.resolve(key):
                settings.set_global(key, value, admin_id=str(request.user.pk))
        return redirect("admin_settings")
    groups = admin_view.group_fields(
        form,
        basic=admin_view.is_basic(request),
        differs=lambda key: settings.resolve(key) != settings.CATALOGUE[key].default,
        skip=(settings.TIME_ZONE,),  # the clock panel shows it
    )
    context = {"form": form, "groups": groups}
    return page(request, "admin/settings.html", context, request.locale)  # type: ignore[attr-defined]
