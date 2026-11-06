"""Further admin accounts (FR-07). All admins are equal (ADR-0014)."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.translation import gettext as _

from app.api.admin_auth import admin_required
from app.api.admin_forms import AdminUserForm
from app.api.rendering import page
from app.kernel import audit


@admin_required
def users(request: HttpRequest) -> HttpResponse:
    manager = get_user_model().objects
    form = AdminUserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = manager.create_admin(
                    form.cleaned_data["login"], form.cleaned_data["password"]
                )
                audit.record(
                    actor_type="admin",
                    actor_id=str(request.user.pk),
                    action="admin.created",
                    entity_type="admin",
                    entity_id=str(user.pk),
                )
        except IntegrityError:  # another admin created the same login at the same moment
            form.add_error("login", _("This login already exists."))
        else:
            return redirect("admin_users")
    context = {"form": form, "admins": manager.order_by("login")}
    return page(request, "admin/users.html", context, request.locale)  # type: ignore[attr-defined]
