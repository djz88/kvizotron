"""Global settings. A quiz can override them on its edit page."""

from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from app.api import admin_view
from app.api.admin_auth import admin_required
from app.api.admin_forms import BrandingForm, GlobalSettingsForm
from app.api.rendering import page
from app.domain import branding, settings


@admin_required
def settings_page(request: HttpRequest, branding_form: BrandingForm | None = None) -> HttpResponse:
    saving = branding_form is None and request.method == "POST"  # else the branding form failed
    form = GlobalSettingsForm(request.POST if saving else None)
    if saving and form.is_valid():
        admin_id = str(request.user.pk)
        with transaction.atomic():  # all keys and the colours, or none
            for key, value in form.cleaned_data.items():
                if key in settings.CATALOGUE and value and value != settings.resolve(key):
                    settings.set_global(key, value, admin_id=admin_id)
            form.save_colours(admin_id)
        return redirect("admin_settings")
    query = request.GET.get("q", "").strip()
    groups = admin_view.group_fields(
        form,
        basic=admin_view.is_basic(request),
        differs=lambda key: (
            admin_view.colours_differ(None)(key)
            if key in admin_view.COLOUR_PLACES
            else settings.resolve(key) != settings.CATALOGUE[key].default
        ),
        extra=admin_view.COLOUR_PLACES,
        skip=(settings.TIME_ZONE,),  # the clock panel shows it
        query=query,
    )
    locale = request.locale  # type: ignore[attr-defined]
    branding_form = branding_form or BrandingForm()
    context = {
        "form": form,
        "groups": groups,
        "query": query,
        "branding_form": branding_form,
        "logo_preview": branding.resolve(None, locale),
        "branding_group": admin_view.branding_group(branding_form, request, None),
        "branding_sources": None,
        "colour_notice": admin_view.adjusted_colours(None, locale),
    }
    return page(request, "admin/settings.html", context, locale)
