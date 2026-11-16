"""Admin accounts (FR-07): create, rename, e-mail, password, block and delete (AC-169).

All admins are equal (ADR-0014). The rules live in `app.domain.admins`.
"""

from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model, update_session_auth_hash
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods, require_POST

from app.api.admin_auth import admin_required
from app.api.admin_common import confirm_page
from app.api.admin_forms import AdminEmailForm, AdminUserForm
from app.api.inline_name import NameField, render_field, wants_partial
from app.api.rendering import page
from app.domain import admins
from app.kernel import audit


@admin_required
def users(request: HttpRequest) -> HttpResponse:
    manager = get_user_model().objects
    if request.method == "POST" and "admin_id" in request.POST:
        return _change_email(request)
    form = AdminUserForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = manager.create_admin(
                    form.cleaned_data["login"], form.cleaned_data["password"]
                )
                if form.cleaned_data["email"]:
                    user.email = form.cleaned_data["email"]
                    user.save(update_fields=["email"])
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
    return _render(request, form)


def _refusal(error: admins.AdminRefused) -> tuple[str, int]:
    """The message and status of a refused change."""
    if isinstance(error, admins.LastAdmin):
        return _("At least one other active admin must remain."), 409
    if isinstance(error, admins.OwnAccount):
        return _("You cannot block or delete your own account."), 409
    if isinstance(error, admins.LoginTaken):
        return _("This login already exists."), 400
    return _("A login must have 1 to 150 characters."), 400


def _login_field(
    admin: Any,
    *,
    editing: bool = False,
    value: str | None = None,
    error: str = "",
    saved: bool = False,
) -> NameField:
    login_url = reverse("admin_user_login", args=[admin.pk])
    page_url = reverse("admin_users")
    return NameField(
        label=_("Login"),
        field="login",
        key=str(admin.pk),
        value=admin.login if value is None else value,
        save_url=login_url,
        edit_url=f"{login_url}?edit=1",
        view_url=login_url,
        edit_page=f"{page_url}?edit=login-{admin.pk}",
        back_page=page_url,
        max_length=get_user_model()._meta.get_field("login").max_length,
        editing=editing,
        error=error,
        saved=saved,
        tag="strong",
        pencil_label=_("Edit the login"),
    )


def _email_form(admin: Any, edited: AdminEmailForm | None) -> AdminEmailForm:
    """The form of one admin; its ids carry the admin's key so no two rows share one."""
    auto_id = f"id_%s_{admin.pk}"
    if edited is not None and str(edited.data.get("admin_id")) == str(admin.pk):
        edited.auto_id = auto_id
        return edited
    return AdminEmailForm(initial={"admin_id": admin.pk, "email": admin.email}, auto_id=auto_id)


def _render(
    request: HttpRequest,
    form: AdminUserForm,
    edited: AdminEmailForm | None = None,
    *,
    notice: str = "",
    status: int = 200,
    field: NameField | None = None,
) -> HttpResponse:
    editing = request.GET.get("edit", "") if request.method == "GET" else ""
    rows = []
    for admin in get_user_model().objects.order_by("login"):
        login = _login_field(admin, editing=editing == f"login-{admin.pk}")
        if field is not None and field.key == str(admin.pk):
            login = field
        rows.append(
            {
                "id": admin.pk,
                "login": admin.login,
                "login_field": login,
                "form": _email_form(admin, edited),
                "is_active": admin.is_active,
                "is_self": admin.pk == request.user.pk,
            }
        )
    context = {"form": form, "admins": rows, "notice": notice}
    return page(request, "admin/users.html", context, request.locale, status=status)  # type: ignore[attr-defined]


def _change_email(request: HttpRequest) -> HttpResponse:
    form = AdminEmailForm(request.POST)
    if form.is_valid():
        updated = get_user_model().objects.filter(pk=form.cleaned_data["admin_id"])
        with transaction.atomic():
            if updated.update(email=form.cleaned_data["email"]) == 0:
                raise Http404
            audit.record(
                actor_type="admin",
                actor_id=str(request.user.pk),
                action="admin.email_changed",
                entity_type="admin",
                entity_id=str(form.cleaned_data["admin_id"]),
            )
        return redirect("admin_users")
    return _render(request, AdminUserForm(), form)


def _admin(admin_id: UUID) -> Any:
    return get_object_or_404(get_user_model(), pk=admin_id)


@admin_required
@require_http_methods(["GET", "POST"])
def user_login(request: HttpRequest, admin_id: UUID) -> HttpResponse:
    """The login of one account on the spot: the display, the field and the save."""
    admin = _admin(admin_id)
    if request.method == "GET":
        editing = request.GET.get("edit") == "1"
        if not wants_partial(request):
            suffix = f"?edit=login-{admin.pk}" if editing else ""
            return redirect(reverse("admin_users") + suffix)
        return render_field(request, _login_field(admin, editing=editing))
    typed = request.POST.get("login", "")
    try:
        admins.rename(admin, typed, actor_id=str(request.user.pk))
    except get_user_model().DoesNotExist as gone:
        raise Http404 from gone
    except admins.AdminRefused as refused:
        error, status = _refusal(refused)
        field = _login_field(admin, editing=True, value=typed, error=error)
        if wants_partial(request):
            return render_field(request, field, status=status)
        return _render(request, AdminUserForm(), status=status, field=field)
    if wants_partial(request):
        return render_field(request, _login_field(admin, saved=True))
    return redirect("admin_users")


@admin_required
@require_POST
def user_password(request: HttpRequest, admin_id: UUID) -> HttpResponse:
    admin = _admin(admin_id)
    own = admin.pk == request.user.pk
    try:
        admins.set_password(
            admin,
            request.POST.get("password", ""),
            actor_id=str(request.user.pk),
            keep_session_key=request.session.session_key if own else None,
        )
    except get_user_model().DoesNotExist as gone:
        raise Http404 from gone
    except ValidationError as refused:
        notice = _("The password of %(login)s was not changed: %(reasons)s") % {
            "login": admin.login,
            "reasons": " ".join(refused.messages),
        }
        return _render(request, AdminUserForm(), notice=notice, status=400)
    if own:  # stay logged in with the new password
        update_session_auth_hash(request, admin)
    return redirect("admin_users")


@admin_required
@require_POST
def user_active(request: HttpRequest, admin_id: UUID) -> HttpResponse:
    admin = _admin(admin_id)
    value = request.POST.get("active")
    if value not in ("0", "1"):
        return HttpResponseBadRequest()
    try:
        admins.set_active(admin, value == "1", actor_id=str(request.user.pk))
    except get_user_model().DoesNotExist as gone:
        raise Http404 from gone
    except admins.AdminRefused as refused:
        notice, status = _refusal(refused)
        return _render(request, AdminUserForm(), notice=notice, status=status)
    return redirect("admin_users")


@admin_required
@require_http_methods(["GET", "POST"])
def user_delete(request: HttpRequest, admin_id: UUID) -> HttpResponse:
    admin = _admin(admin_id)
    if admin.pk == request.user.pk:
        notice, status = _refusal(admins.OwnAccount())
        return _render(request, AdminUserForm(), notice=notice, status=status)
    if request.method == "GET" or request.POST.get("confirm") != "1":
        return confirm_page(
            request,
            message=_(
                "Delete the admin account %(login)s? It can no longer log in. "
                "Quizzes it created stay."
            )
            % {"login": admin.login},
            action=reverse("admin_user_delete", args=[admin.pk]),
            cancel=reverse("admin_users"),
        )
    try:
        admins.delete(admin, actor_id=str(request.user.pk))
    except get_user_model().DoesNotExist as gone:
        raise Http404 from gone
    except admins.AdminRefused as refused:
        notice, status = _refusal(refused)
        return _render(request, AdminUserForm(), notice=notice, status=status)
    return redirect("admin_users")
