"""Login and logout pages (FR-07). The active auth provider decides through Django's backends."""

from collections.abc import Callable
from functools import wraps
from urllib.parse import quote

from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from app.api.admin_forms import LoginForm
from app.api.rendering import page


def admin_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    @wraps(view)
    @never_cache
    def wrapper(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        if not request.user.is_authenticated:
            login_url = reverse("admin_login")
            if request.method != "GET":  # most such routes would answer a return by GET with 405
                return redirect(login_url)
            return redirect(f"{login_url}?next={quote(request.get_full_path())}")
        return view(request, *args, **kwargs)

    return wrapper


def _safe_next(request: HttpRequest, target: str) -> str:
    allowed = url_has_allowed_host_and_scheme(
        target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )
    return target if allowed else reverse("admin_quizzes")


@never_cache
def login_page(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("admin_quizzes")
    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            username=form.cleaned_data["login"],
            password=form.cleaned_data["password"],
        )
        if user is not None:
            login(request, user)
            return redirect(_safe_next(request, request.POST.get("next", "")))
        error = _("Wrong login or password.")
    context = {
        "form": form,
        "error": error,
        "next": request.POST.get("next") or request.GET.get("next", ""),
    }
    return page(request, "admin/login.html", context, request.locale)  # type: ignore[attr-defined]


@require_POST
def logout_page(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("admin_login")


@admin_required
def index(request: HttpRequest) -> HttpResponse:
    return redirect("admin_quizzes")
