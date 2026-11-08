"""Reward rules of a quiz's template and of a run, the run's entitlements and its draw page
(FR-36, FR-37, FR-38).

The rules decide nothing here: `app/domain/rewards.py` checks the structure, what may change on
an open run and what conflicts with the run's settings. These views only turn its refusals into
messages. E-mails are shown on the run's rewards page only, which needs a login like every admin
page.
"""

from typing import Any
from uuid import UUID

from django.contrib.auth import get_user_model
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import pgettext
from django.views.decorators.http import require_POST

from app.api.admin_auth import admin_required
from app.api.admin_forms import RewardRuleForm
from app.api.admin_workspace import workspace
from app.api.rendering import page
from app.contracts import REWARD_RUN_KEYS, REWARD_SOURCE
from app.domain import authoring, draws, results, rewards, settings
from app.domain.models import (
    Draw,
    DrawEntry,
    Participant,
    Quiz,
    QuizRun,
    RewardEntitlement,
    RewardRule,
)


def _locales(quiz: Quiz) -> list[str]:
    """The quiz's languages, its default first: the name is required there."""
    others = [code for code in quiz.supported_locales if code != quiz.default_locale]
    return [quiz.default_locale, *others]


def _kind_labels() -> dict[str, str]:
    return {
        RewardRule.Kind.THRESHOLD: _("Threshold"),
        RewardRule.Kind.PARTICIPATION: _("Participation"),
        RewardRule.Kind.MANUAL: _("Manual"),
        RewardRule.Kind.DRAW: _("Draw"),
    }


def _status_labels() -> dict[str, str]:
    return {
        RewardEntitlement.Status.GRANTED: pgettext("reward", "Granted"),
        RewardEntitlement.Status.HANDED_OVER: pgettext("reward", "Handed over"),
        RewardEntitlement.Status.CANCELLED: pgettext("reward", "Cancelled"),
    }


def _source_labels() -> dict[str, str]:
    return {
        RewardEntitlement.Source.AUTO: _("Automatic"),
        RewardEntitlement.Source.MANUAL: _("By an admin"),
        RewardEntitlement.Source.DRAW: _("Draw"),
    }


def _reason_label(reason: str) -> str:
    return _("No longer reached") if reason == rewards.NO_LONGER_REACHED else reason


def _rule_form(rule: RewardRule, locked: bool, data: Any = None) -> RewardRuleForm:
    return RewardRuleForm(
        data,
        locales=_locales(rule.quiz),
        structure_locked=locked,
        initial=RewardRuleForm.initial_of(rule),
        auto_id=f"rule-{rule.id}-%s",
    )


def _new_form(quiz: Quiz, data: Any = None) -> RewardRuleForm:
    return RewardRuleForm(
        data, locales=_locales(quiz), structure_locked=False, auto_id="rule-new-%s"
    )


def _rule_rows(
    rules: list[RewardRule],
    locale: str,
    locked: bool,
    bound: tuple[RewardRule, RewardRuleForm] | None,
) -> list[dict[str, Any]]:
    kinds = _kind_labels()
    rows = []
    for rule in rules:
        form = bound[1] if bound and bound[0].pk == rule.pk else _rule_form(rule, locked)
        rows.append(
            {
                "rule": rule,
                "form": form,
                "name": rewards.text(rule, rule.quiz, locale, "name"),
                "description": rewards.text(rule, rule.quiz, locale, "description"),
                "claim": rewards.text(rule, rule.quiz, locale, "claim"),
                "kind": kinds.get(rule.kind, rule.kind),
            }
        )
    return rows


def _setting_rows(values: dict[str, str]) -> list[tuple[str, str]]:
    return [
        (settings.CATALOGUE[key].label, settings.CATALOGUE[key].value_labels[value])
        for key, value in values.items()
    ]


# The quiz's template ---------------------------------------------------------------------------


def _quiz_page(
    request: HttpRequest,
    quiz: Quiz,
    *,
    new_form: RewardRuleForm | None = None,
    bound: tuple[RewardRule, RewardRuleForm] | None = None,
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    source = settings.resolve(REWARD_SOURCE, quiz=quiz)
    context = workspace(quiz, "rewards", error) | {
        "rules": _rule_rows(rewards.template_of(quiz), locale, False, bound),
        "new_form": new_form or _new_form(quiz),
        "new_action": reverse("admin_quiz_reward_new", args=[quiz.id]),
        "source": settings.CATALOGUE[REWARD_SOURCE].value_labels[source],
        "source_label": settings.CATALOGUE[REWARD_SOURCE].label,
        "run_settings": _setting_rows(rewards.rules_for_quiz(quiz)),
        "editable": quiz.archived_at is None,
    }
    return page(request, "admin/rewards.html", context, locale, status=status)


@admin_required
def quiz_rewards(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    return _quiz_page(request, get_object_or_404(Quiz, pk=quiz_id))


@admin_required
@require_POST
def quiz_reward_new(request: HttpRequest, quiz_id: UUID) -> HttpResponse:
    quiz = get_object_or_404(Quiz, pk=quiz_id)
    form = _new_form(quiz, request.POST)
    if not form.is_valid():
        return _quiz_page(request, quiz, new_form=form, status=400)
    try:
        rewards.save_rule(
            quiz, form.rule_data(form.texts()), rule=None, admin_id=str(request.user.pk)
        )
    except rewards.RuleInvalid as refused:
        form.refuse(refused.code)
        return _quiz_page(request, quiz, new_form=form, status=400)
    except authoring.QuizArchived:
        return _quiz_page(request, quiz, new_form=form, error=_archived(), status=409)
    return redirect("admin_quiz_rewards", quiz.id)


def _archived() -> str:
    return _("The quiz is archived. Restore it to change its rewards.")


def _locked() -> str:
    return _("The kind, threshold and counts can change only while the run is planned.")


# A run -----------------------------------------------------------------------------------------


def _run(run_id: UUID) -> QuizRun:
    """A normal run: a test run never has rewards (ADR-0044)."""
    return get_object_or_404(QuizRun.objects.select_related("quiz"), pk=run_id)


def _entitlement_rows(run: QuizRun, locale: str, numbers: dict[str, int]) -> list[dict[str, Any]]:
    statuses, sources = _status_labels(), _source_labels()
    rows = []
    for row in rewards.of_run(run):
        who = row.participant
        rows.append(
            {
                "id": row.id,
                "name": who.display_name
                or results.anonymous_label(run.quiz, locale, numbers.get(str(who.id), 0)),
                "email": who.email or "",
                "rule": rewards.text(row.rule, run.quiz, locale, "name"),
                "status": row.status,
                "status_label": statuses.get(row.status, row.status),
                "source": sources.get(row.source, row.source),
                "reason": _reason_label(row.reason),
                "can_hand_over": row.status == RewardEntitlement.Status.GRANTED,
                "can_cancel": row.status != RewardEntitlement.Status.CANCELLED,
            }
        )
    return rows


def _grantable(run: QuizRun, locale: str, numbers: dict[str, int]) -> list[tuple[UUID, str]]:
    return [
        (
            who.id,
            who.display_name
            or results.anonymous_label(run.quiz, locale, numbers.get(str(who.id), 0)),
        )
        for who in rewards.grantable(run)
    ]


def _run_page(
    request: HttpRequest,
    run: QuizRun,
    *,
    new_form: RewardRuleForm | None = None,
    bound: tuple[RewardRule, RewardRuleForm] | None = None,
    error: str | None = None,
    status: int = 200,
) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    quiz = run.quiz
    planned = run.status == QuizRun.Status.SCHEDULED
    rules = rewards.rules_of(run)
    rows = _rule_rows(rules, locale, not planned, bound)
    numbers = results.participant_numbers(run)
    context = workspace(quiz, "runs", error) | {
        "run": run,
        "planned": planned,
        "rules": rows,
        "new_form": (new_form or _new_form(quiz)) if planned else None,
        "new_action": reverse("admin_run_reward_new", args=[run.id]),
        "run_settings": _setting_rows({key: rewards.of(run)[key] for key in REWARD_RUN_KEYS}),
        "contact_warning": rewards.contact_warning(run),
        "conflicts": rewards.messages(rewards.conflicts(run)),
        "entitlements": _entitlement_rows(run, locale, numbers),
        "manual_rules": [row for row in rows if row["rule"].kind == RewardRule.Kind.MANUAL],
        "grantable": _grantable(run, locale, numbers),
        "has_draw": any(rule.kind == RewardRule.Kind.DRAW for rule in rules),
    }
    return page(request, "admin/rewards.html", context, locale, status=status)


@admin_required
def run_rewards(request: HttpRequest, run_id: UUID) -> HttpResponse:
    return _run_page(request, _run(run_id))


@admin_required
@require_POST
def run_reward_new(request: HttpRequest, run_id: UUID) -> HttpResponse:
    run = _run(run_id)
    form = _new_form(run.quiz, request.POST)
    if not form.is_valid():
        return _run_page(request, run, new_form=form, status=400)
    try:
        rewards.save_rule(
            run, form.rule_data(form.texts()), rule=None, admin_id=str(request.user.pk)
        )
    except rewards.RuleInvalid as refused:
        form.refuse(refused.code)
        return _run_page(request, run, new_form=form, status=400)
    except rewards.RuleLocked:
        return _run_page(request, run, error=_locked(), status=409)
    except rewards.RewardConflict as conflict:
        return _run_page(
            request, run, new_form=form, error=" ".join(conflict.messages()), status=409
        )
    return redirect("admin_run_rewards", run.id)


# One rule --------------------------------------------------------------------------------------


def _rule_page(request: HttpRequest, rule: RewardRule, **kwargs: Any) -> HttpResponse:
    if rule.run is not None:
        return _run_page(request, rule.run, **kwargs)
    return _quiz_page(request, rule.quiz, **kwargs)


def _rule_saved(rule: RewardRule) -> HttpResponse:
    if rule.run_id is not None:
        return redirect("admin_run_rewards", rule.run_id)
    return redirect("admin_quiz_rewards", rule.quiz_id)


def _delete(request: HttpRequest, rule: RewardRule) -> HttpResponse:
    try:
        rewards.delete_rule(rule, admin_id=str(request.user.pk))
    except rewards.RuleLocked:
        return _rule_page(request, rule, error=_locked(), status=409)
    except authoring.QuizArchived:
        return _rule_page(request, rule, error=_archived(), status=409)
    return _rule_saved(rule)


@admin_required
@require_POST
def reward_rule(request: HttpRequest, rule_id: UUID) -> HttpResponse:
    """Saves a rule, or deletes it with `action=delete`. On an open run only the texts change."""
    rule = get_object_or_404(
        RewardRule.objects.select_related("quiz", "run").exclude(run__kind=QuizRun.Kind.TEST),
        pk=rule_id,
    )
    if request.POST.get("action") == "delete":
        return _delete(request, rule)
    locked = rule.run is not None and rule.run.status != QuizRun.Status.SCHEDULED
    form = _rule_form(rule, locked, request.POST)
    if not form.is_valid():
        return _rule_page(request, rule, bound=(rule, form), status=400)
    # Texts of languages the quiz no longer offers stay as they were.
    texts = dict(rule.texts_json or {}) | form.texts()
    admin_id = str(request.user.pk)
    try:
        if locked:
            if not RewardRule.objects.filter(pk=rule.pk).exists():
                raise Http404
            rewards.save_texts(rule, texts, admin_id=admin_id)
        else:
            owner: Quiz | QuizRun = rule.run if rule.run is not None else rule.quiz
            rewards.save_rule(owner, form.rule_data(texts), rule=rule, admin_id=admin_id)
    except RewardRule.DoesNotExist as gone:  # deleted while the form was open
        raise Http404 from gone
    except rewards.RuleInvalid as refused:
        form.refuse(refused.code)
        return _rule_page(request, rule, bound=(rule, form), status=400)
    except rewards.RuleLocked:
        return _rule_page(request, rule, error=_locked(), status=409)
    except rewards.RewardConflict as conflict:
        error = " ".join(conflict.messages())
        return _rule_page(request, rule, bound=(rule, form), error=error, status=409)
    except authoring.QuizArchived:
        return _rule_page(request, rule, error=_archived(), status=409)
    return _rule_saved(rule)


# Entitlements ----------------------------------------------------------------------------------


def _uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise Http404 from exc


@admin_required
@require_POST
def entitlement(request: HttpRequest, entitlement_id: UUID) -> HttpResponse:
    """`action` is `hand_over`, or `cancel` with a `reason`."""
    row = get_object_or_404(
        RewardEntitlement.objects.select_related("run__quiz"), pk=entitlement_id
    )
    run = row.run
    action = request.POST.get("action", "")
    admin_id = str(request.user.pk)
    try:
        if action == "hand_over":
            rewards.hand_over(row, admin_id=admin_id)
        elif action == "cancel":
            rewards.cancel(row, request.POST.get("reason", ""), admin_id=admin_id)
        else:
            return HttpResponseBadRequest()
    except rewards.RuleInvalid as refused:
        if refused.code == "reason":
            error = _("Enter a reason, at most 200 characters.")
            return _run_page(request, run, error=error, status=400)
        error = _("The reward has changed in the meantime. Check its status and try again.")
        return _run_page(request, run, error=error, status=409)
    return redirect("admin_run_rewards", run.id)


@admin_required
@require_POST
def reward_grant(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """A manual reward for one participant of this run."""
    run = _run(run_id)
    rule = get_object_or_404(
        RewardRule,
        pk=_uuid(request.POST.get("rule", "")),
        run=run,
        kind=RewardRule.Kind.MANUAL,
    )
    participant = get_object_or_404(
        Participant, pk=_uuid(request.POST.get("participant", "")), run=run
    )
    try:
        rewards.grant_manual(rule, participant, admin_id=str(request.user.pk))
    except rewards.RuleInvalid, rewards.RuleLocked:
        return _run_page(request, run, error=_("This reward cannot be granted."), status=409)
    return redirect("admin_run_rewards", run.id)


# The draw page ---------------------------------------------------------------------------------


def _draw_refusals() -> dict[str, str]:
    return {
        "run_not_closed": _("A draw is possible only after the run has closed."),
        "stateless": _("This run keeps no scores, so there is nobody to draw from."),
        "grading_pending": _("Some answers still wait for grading. Grade them before the draw."),
        "not_a_draw_rule": _("This reward is not a draw."),
        "nobody_eligible": _("Nobody is eligible for this draw."),
        "nobody_left": _("Everybody eligible has already been drawn."),
        "no_alternate": _("No alternate who is still eligible is left. Draw a substitute instead."),
        "already_drawn": _("This reward has already been drawn. A redraw draws it again."),
        "not_drawn": _(
            "This reward has not been drawn yet, or its winners have changed in the meantime."
        ),
        "reason_missing": _("Enter a reason, at most 200 characters."),
    }


def _draw_action_labels() -> dict[str, str]:
    return {
        Draw.Action.DRAW: _("First draw"),
        Draw.Action.REDRAW: _("Redraw"),
        Draw.Action.MOVE_UP: _("Alternate moved up"),
        Draw.Action.SUBSTITUTE: _("Substitute drawn"),
    }


def _person(participant: Participant | None, run: QuizRun, locale: str, numbers: dict) -> dict:
    if participant is None:
        return {"name": _("No longer stored"), "email": ""}
    name = participant.display_name or results.anonymous_label(
        run.quiz, locale, numbers.get(str(participant.id), 0)
    )
    return {"name": name, "email": participant.email or ""}


def _entry_row(entry: DrawEntry, run: QuizRun, locale: str, numbers: dict) -> dict[str, Any]:
    return {"id": entry.id, "position": entry.position} | _person(
        entry.participant, run, locale, numbers
    )


def _draw_section(
    rule: RewardRule, run: QuizRun, locale: str, numbers: dict, admins: dict[str, str]
) -> dict[str, Any]:
    refusal = draws.refusal(rule)
    preview = None
    if refusal is None:
        snapshot = draws.preview(rule)
        found = Participant.objects.in_bulk(snapshot.participant_ids)
        preview = {
            "count": len(snapshot.participant_ids),
            "fingerprint": snapshot.fingerprint,
            "people": [
                _person(found.get(UUID(who)), run, locale, numbers)
                for who in snapshot.participant_ids
            ],
        }
    standing = draws.standing(rule)
    labels = _draw_action_labels()
    history = [
        {
            "when": row.created_at,
            "admin": admins.get(row.admin_id, row.admin_id),
            "action": labels.get(row.action, row.action),
            "reason": row.reason,
            "count": row.eligible_count,
            "fingerprint": row.eligible_set_hash,
            "algorithm": row.algorithm,
            "selected": row.audit_json.get("count", 0),
            "requested": row.audit_json.get("requested", 0),
            "superseded": row.id not in standing.chain,
        }
        for row in standing.history
    ]
    return {
        "rule": rule,
        "name": rewards.text(rule, run.quiz, locale, "name"),
        "refusal": _draw_refusals().get(refusal, refusal) if refusal else None,
        "preview": preview,
        "nobody": preview is not None and preview["count"] == 0,
        "nobody_text": _draw_refusals()["nobody_eligible"],
        "drawn": standing.draw is not None,
        "winners": [_entry_row(entry, run, locale, numbers) for entry in standing.winners],
        "alternates": [_entry_row(entry, run, locale, numbers) for entry in standing.alternates],
        "history": list(reversed(history)),
        "public": rule.winners_public,
    }


def _draw_page(
    request: HttpRequest, run: QuizRun, *, error: str | None = None, status: int = 200
) -> HttpResponse:
    locale = request.locale  # type: ignore[attr-defined]
    numbers = results.participant_numbers(run)
    admins = {str(pk): login for pk, login in get_user_model().objects.values_list("pk", "login")}
    rules = [rule for rule in rewards.rules_of(run) if rule.kind == RewardRule.Kind.DRAW]
    context = workspace(run.quiz, "runs", error) | {
        "run": run,
        "sections": [_draw_section(rule, run, locale, numbers, admins) for rule in rules],
    }
    return page(request, "admin/prize_draw.html", context, locale, status=status)


@admin_required
def run_draw(request: HttpRequest, run_id: UUID) -> HttpResponse:
    """Reads only: the preview is built again by the draw itself."""
    return _draw_page(request, _run(run_id))


@admin_required
@require_POST
def run_draw_action(request: HttpRequest, run_id: UUID, rule_id: UUID) -> HttpResponse:
    """`action` is draw, redraw, move_up, substitute (with `entry`), publish or unpublish."""
    run = _run(run_id)
    rule = get_object_or_404(RewardRule, pk=rule_id, run=run, kind=RewardRule.Kind.DRAW)
    action = request.POST.get("action", "")
    reason = request.POST.get("reason", "")
    admin_id = str(request.user.pk)
    try:
        if action == "draw":
            draws.draw(rule, admin_id=admin_id)
        elif action == "redraw":
            draws.redraw(rule, reason, admin_id=admin_id)
        elif action in ("move_up", "substitute"):
            entry = get_object_or_404(
                DrawEntry,
                pk=_uuid(request.POST.get("entry", "")),
                draw__rule=rule,
                role=DrawEntry.Role.WINNER,
            )
            replace = draws.move_up if action == "move_up" else draws.substitute
            replace(rule, entry, reason, admin_id=admin_id)
        elif action in ("publish", "unpublish"):
            draws.set_public(rule, action == "publish", admin_id=admin_id)
        else:
            return HttpResponseBadRequest()
    except draws.DrawRefused as refused:
        status = 400 if refused.reason == "reason_missing" else 409
        error = _draw_refusals().get(refused.reason, refused.reason)
        return _draw_page(request, run, error=error, status=status)
    return redirect(reverse("admin_run_draw", args=[run.id]) + f"#rule-{rule.id}")
