"""Subscriber-facing endpoints for email digests (#231).

Auth model (no accounts, no passwords):

- **Subscribe** is public: rate-limited (5/h per IP, 1/h per email hash),
  honeypot-guarded, and always answers 202 without revealing whether the
  address was already known. Double opt-in — nothing is ever sent to an
  address that hasn't clicked its verification link.
- **Verification** is a one-shot random token stored on the row.
- **Manage/unsubscribe** links carry stateless HMAC tokens
  (``services/tokens.py``). The manage link trades its token for a
  short-lived session cookie and redirects to the React preferences page,
  so the token doesn't linger in the SPA's URL bar/history.
- The preferences API is session-authenticated and CSRF-protected (SameSite
  cookies + X-CSRFToken). The unsubscribe POST is ``csrf_exempt`` because
  mail providers' one-click unsubscribe POSTs can't carry a CSRF token —
  the HMAC token *is* the auth.

Raw emails never reach logs — log lines use ``subscriber.id`` and the
console handler additionally runs ``EmailRedactionFilter``.
"""
import hashlib
import json
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_ratelimit.decorators import ratelimit

from .models import Subscriber, SubscriberPreferences, validate_issue_areas
from .services.email_client import get_email_client
from .services.tokens import (
    PURPOSE_MANAGE,
    PURPOSE_UNSUBSCRIBE,
    make_token,
    verify_token,
)

logger = logging.getLogger(__name__)

SESSION_KEY = "digest_subscriber_id"
SESSION_TTL_SECONDS = 3600


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #

def _email_hash_key(group, request):
    """Rate-limit key: SHA-256 of the submitted email. Hashed so the raw
    address never enters the cache key namespace (cache keys can surface
    in debug tooling)."""
    try:
        email = json.loads(request.body).get("email", "")
    except (ValueError, AttributeError):
        email = ""
    if not isinstance(email, str) or not email:
        return "invalid"
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _rate_limited_response():
    response = JsonResponse(
        {"error": "Too many requests. Please try again later."}, status=429
    )
    response["Retry-After"] = "3600"
    return response


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def _validate_and_apply_preferences(prefs: SubscriberPreferences, data: dict):
    """Validate every preference field in ``data`` before applying any of
    them, then save. Raises ValidationError with a user-facing message.

    All id lookups go through the ORM (parameterized queries)."""
    from councilmatic_core.models import Bill
    from opencivicdata.core.models import Person
    from reps.models import District

    errors = []

    issue_areas = data.get("issue_areas")
    if issue_areas is not None:
        try:
            validate_issue_areas(issue_areas)
        except ValidationError as exc:
            errors.extend(exc.messages)

    rep_ids = data.get("followed_rep_ids")
    reps = None
    if rep_ids is not None:
        if not isinstance(rep_ids, list):
            errors.append("followed_rep_ids must be a list.")
        else:
            reps = list(Person.objects.filter(id__in=rep_ids))
            if len(reps) != len(set(rep_ids)):
                errors.append("One or more followed_rep_ids are unknown.")

    bill_ids = data.get("followed_bill_ids")
    bills = None
    if bill_ids is not None:
        if not isinstance(bill_ids, list):
            errors.append("followed_bill_ids must be a list.")
        else:
            bills = list(Bill.objects.filter(id__in=bill_ids))
            if len(bills) != len(set(bill_ids)):
                errors.append("One or more followed_bill_ids are unknown.")

    district = None
    district_id = data.get("district_id")
    if district_id is not None:
        district = District.objects.filter(pk=district_id).first()
        if district is None:
            errors.append("Unknown district_id.")

    if errors:
        raise ValidationError(errors)

    if "weekly_enabled" in data:
        prefs.weekly_enabled = bool(data["weekly_enabled"])
    if "daily_enabled" in data:
        prefs.daily_enabled = bool(data["daily_enabled"])
    if issue_areas is not None:
        prefs.issue_areas = issue_areas
    if "district_id" in data:
        prefs.district = district
    prefs.save()
    if reps is not None:
        prefs.followed_reps.set(reps)
    if bills is not None:
        prefs.followed_bills.set(bills)


def _send_verification_email(request, subscriber):
    confirm_url = request.build_absolute_uri(
        f"/digests/confirm?token={subscriber.verification_token}"
    )
    context = {"confirm_url": confirm_url}
    get_email_client().send(
        to=subscriber.email,
        subject="Confirm your Seattle Councilmatic digest subscription",
        text_body=render_to_string("email/verify.txt", context),
        html_body=render_to_string("email/verify.html", context),
    )


def _send_manage_link_email(request, subscriber):
    manage_url = request.build_absolute_uri(
        f"/digests/manage?token={make_token(subscriber, PURPOSE_MANAGE)}"
    )
    context = {"manage_url": manage_url}
    get_email_client().send(
        to=subscriber.email,
        subject="Manage your Seattle Councilmatic digest preferences",
        text_body=render_to_string("email/manage_link.txt", context),
        html_body=render_to_string("email/manage_link.html", context),
    )


def _preferences_payload(request, subscriber):
    prefs = subscriber.preferences
    return {
        "status": subscriber.status,
        "email_masked": _mask_email(subscriber.email),
        "weekly_enabled": prefs.weekly_enabled,
        "daily_enabled": prefs.daily_enabled,
        "issue_areas": prefs.issue_areas,
        "followed_rep_ids": list(prefs.followed_reps.values_list("id", flat=True)),
        "followed_bills": [
            {"id": b["id"], "identifier": b["identifier"], "title": b["title"]}
            for b in prefs.followed_bills.values("id", "identifier", "title")
        ],
        "district_id": prefs.district_id,
        "unsubscribe_url": request.build_absolute_uri(
            f"/digests/unsubscribe?token={make_token(subscriber, PURPOSE_UNSUBSCRIBE)}"
        ),
    }


# --------------------------------------------------------------------- #
# API endpoints
# --------------------------------------------------------------------- #

@csrf_exempt  # Public unauthenticated endpoint; abuse controls are the rate limits + honeypot.
@require_POST
@ratelimit(key="ip", rate="5/h", method="POST", block=False)
@ratelimit(key=_email_hash_key, rate="1/h", method="POST", block=False)
def subscribe(request):
    """POST /api/digests/subscribe

    Body: {email, weekly_enabled?, daily_enabled?, issue_areas?[],
    followed_rep_ids?[], followed_bill_ids?[], district_id?, website?}.

    Always 202 on well-formed input — the response never discloses whether
    the address was already subscribed (enumeration guard). ``website`` is
    the honeypot: humans never see it, bots fill it, we accept-and-drop.
    """
    # Launch gate / kill switch: signups closed unless DIGESTS_ENABLED.
    # Existing-subscriber self-service (confirm/manage/preferences/
    # unsubscribe/manage-link) deliberately stays up — see settings.py.
    if not settings.DIGESTS_ENABLED:
        return JsonResponse({"error": "Digest signups aren't open yet."}, status=403)

    if getattr(request, "limited", False):
        return _rate_limited_response()

    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    # Honeypot: pretend success, do nothing.
    if data.get("website"):
        return JsonResponse({"status": "ok"}, status=202)

    email = data.get("email", "")
    if not isinstance(email, str):
        return JsonResponse({"error": "email must be a string."}, status=400)
    email = email.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Please enter a valid email address."}, status=400)

    subscriber = Subscriber.objects.filter(email=email).first()
    if subscriber and subscriber.status == Subscriber.STATUS_ACTIVE:
        # Already subscribed — same 202, no email, no state change.
        return JsonResponse({"status": "ok"}, status=202)

    if subscriber is None:
        subscriber = Subscriber(email=email)
    # New signup, pending re-send, or re-opt-in after unsubscribe/bounce:
    # all converge on a fresh pending verification round-trip.
    subscriber.status = Subscriber.STATUS_PENDING
    subscriber.verification_token = get_random_string(43)
    subscriber.save()

    prefs, _ = SubscriberPreferences.objects.get_or_create(subscriber=subscriber)
    try:
        _validate_and_apply_preferences(prefs, data)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)

    try:
        _send_verification_email(request, subscriber)
    except Exception:
        logger.exception(
            "Verification email send failed for subscriber %s", subscriber.pk
        )
        return JsonResponse(
            {"error": "Could not send the verification email. Please try again later."},
            status=500,
        )

    logger.info("Verification email sent for subscriber %s", subscriber.pk)
    return JsonResponse({"status": "ok"}, status=202)


@csrf_exempt  # Public unauthenticated endpoint; same abuse controls as subscribe.
@require_POST
@ratelimit(key="ip", rate="5/h", method="POST", block=False)
@ratelimit(key=_email_hash_key, rate="1/h", method="POST", block=False)
def send_manage_link(request):
    """POST /api/digests/manage-link — body: {email}.

    Self-service recovery for the preferences page: emails a fresh manage
    link to an *active* subscriber (a *pending* one gets their verification
    email re-sent instead — the manage page is useless until they confirm).
    Always 202 on well-formed input, whether or not the address is
    subscribed — same enumeration guard as subscribe.
    """
    if getattr(request, "limited", False):
        return _rate_limited_response()

    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"error": "Invalid JSON body."}, status=400)

    email = data.get("email", "")
    if not isinstance(email, str):
        return JsonResponse({"error": "email must be a string."}, status=400)
    email = email.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse({"error": "Please enter a valid email address."}, status=400)

    subscriber = Subscriber.objects.filter(email=email).first()
    try:
        if subscriber and subscriber.status == Subscriber.STATUS_ACTIVE:
            _send_manage_link_email(request, subscriber)
            logger.info("Manage link sent for subscriber %s", subscriber.pk)
        elif subscriber and subscriber.status == Subscriber.STATUS_PENDING:
            if not subscriber.verification_token:
                subscriber.verification_token = get_random_string(43)
                subscriber.save(update_fields=["verification_token"])
            _send_verification_email(request, subscriber)
            logger.info("Verification email re-sent for subscriber %s", subscriber.pk)
        # Unknown / unsubscribed / bounced: silently no-op — the 202 below
        # is identical either way.
    except Exception:
        logger.exception(
            "Manage-link email send failed for subscriber %s",
            subscriber.pk if subscriber else "?",
        )
        return JsonResponse(
            {"error": "Could not send the email. Please try again later."},
            status=500,
        )
    return JsonResponse({"status": "ok"}, status=202)


@require_GET
def options(request):
    """GET /api/digests/options — vocabulary the subscribe/preferences forms
    render: issue-area tags, current councilmembers, districts."""
    from reps.services import _query_current_council_members
    from reps.models import District
    from seattle_app.services.claude_service import BILL_TAG_VOCABULARY

    reps = [
        {"id": person_id, "name": name, "seat": label}
        for name, _slug, label, person_id in _query_current_council_members()
    ]
    districts = [
        {"id": d.pk, "number": d.number, "name": d.name, "description": d.description}
        for d in District.objects.order_by("number")
    ]
    return JsonResponse({
        # The SPA's SubscribeForm keys off this: closed → homepage embed
        # renders nothing, /digests/subscribe shows a coming-soon notice.
        "signup_open": settings.DIGESTS_ENABLED,
        "issue_areas": list(BILL_TAG_VOCABULARY),
        "reps": reps,
        "districts": districts,
    })


@ensure_csrf_cookie
@require_http_methods(["GET", "POST"])
def preferences_api(request):
    """GET/POST /api/digests/preferences — session-authenticated (the
    session comes from the manage link). POST is CSRF-protected: the SPA
    reads the ``csrftoken`` cookie (set on GET) into ``X-CSRFToken``."""
    subscriber_id = request.session.get(SESSION_KEY)
    subscriber = (
        Subscriber.objects.filter(pk=subscriber_id).select_related("preferences").first()
        if subscriber_id
        else None
    )
    if subscriber is None:
        return JsonResponse(
            {"error": "Not authenticated. Use the manage link from a digest email."},
            status=401,
        )

    # Sliding expiry: any authenticated interaction resets the 1-hour
    # clock, so the session can't lapse mid-edit. Idle sessions still
    # die after SESSION_TTL_SECONDS.
    request.session.set_expiry(SESSION_TTL_SECONDS)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
        except ValueError:
            return JsonResponse({"error": "Invalid JSON body."}, status=400)
        try:
            _validate_and_apply_preferences(subscriber.preferences, data)
        except ValidationError as exc:
            return JsonResponse({"error": " ".join(exc.messages)}, status=400)
        logger.info("Preferences updated for subscriber %s", subscriber.pk)

    return JsonResponse(_preferences_payload(request, subscriber))


# --------------------------------------------------------------------- #
# Server-rendered pages (token entry points from email links)
# --------------------------------------------------------------------- #

@require_GET
def confirm(request):
    """GET /digests/confirm?token=... — the double-opt-in click."""
    token = request.GET.get("token", "")
    subscriber = (
        Subscriber.objects.filter(verification_token=token).first() if token else None
    )
    if subscriber is None:
        # Unknown OR already-used token. The page stays generic — a used
        # token is most often a re-click of a link that already worked.
        return render(request, "digests/token_invalid.html", {
            "message": "This confirmation link is invalid or was already used. "
            "If you already confirmed, you're all set — otherwise subscribe "
            "again to get a fresh link.",
        }, status=404)

    subscriber.status = Subscriber.STATUS_ACTIVE
    subscriber.verification_token = None
    subscriber.verified_at = timezone.now()
    subscriber.unsubscribed_at = None
    subscriber.save()
    SubscriberPreferences.objects.get_or_create(subscriber=subscriber)
    logger.info("Subscriber %s verified", subscriber.pk)

    manage_url = request.build_absolute_uri(
        f"/digests/manage?token={make_token(subscriber, PURPOSE_MANAGE)}"
    )
    return render(request, "digests/confirm_result.html", {
        "email_masked": _mask_email(subscriber.email),
        "manage_url": manage_url,
    })


@require_GET
def manage(request):
    """GET /digests/manage?token=... — trade the HMAC manage token for a
    short-lived session and land on the React preferences page (keeps the
    token out of the SPA's URL/history)."""
    subscriber = verify_token(request.GET.get("token", ""), PURPOSE_MANAGE)
    if subscriber is None:
        return render(request, "digests/token_invalid.html", {
            "message": "This manage link is invalid or has been revoked. "
            "Use the link from your most recent digest email.",
        }, status=404)
    request.session[SESSION_KEY] = subscriber.pk
    request.session.set_expiry(SESSION_TTL_SECONDS)
    return redirect("/digests/preferences")


@csrf_exempt  # One-click unsubscribe POSTs (RFC 8058) carry no CSRF token; the HMAC token is the auth.
@require_http_methods(["GET", "POST"])
def unsubscribe(request):
    """GET renders a confirm page; POST (from that page's form, or a mail
    provider's one-click POST) flips the subscriber to unsubscribed.
    An optional ``delete_now`` form field hard-deletes the row immediately
    instead of waiting out the purge_unsubscribed retention window."""
    token = request.POST.get("token") or request.GET.get("token", "")
    subscriber = verify_token(token, PURPOSE_UNSUBSCRIBE)
    if subscriber is None:
        return render(request, "digests/token_invalid.html", {
            "message": "This unsubscribe link is invalid or has been revoked. "
            "Use the link from your most recent digest email.",
        }, status=404)

    if request.method == "GET":
        return render(request, "digests/unsubscribe_confirm.html", {
            "email_masked": _mask_email(subscriber.email),
            "token": token,
            "already_unsubscribed": subscriber.status == Subscriber.STATUS_UNSUBSCRIBED,
        })

    deleted = False
    if request.POST.get("delete_now"):
        logger.info("Subscriber %s deleted on request", subscriber.pk)
        subscriber.delete()
        deleted = True
    elif subscriber.status != Subscriber.STATUS_UNSUBSCRIBED:
        subscriber.mark_unsubscribed()
        logger.info("Subscriber %s unsubscribed", subscriber.pk)

    # RFC 8058 one-click POSTs come from the mail provider, not a browser;
    # they only need the 2xx.
    if request.POST.get("List-Unsubscribe") == "One-Click":
        return HttpResponse("Unsubscribed.", content_type="text/plain")

    return render(request, "digests/unsubscribe_done.html", {"deleted": deleted})
