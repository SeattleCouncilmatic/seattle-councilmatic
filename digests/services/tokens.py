"""Stateless HMAC tokens for manage/unsubscribe links (#231).

Token = ``"<subscriber_id>.<hex sig>"`` where the signature is
HMAC-SHA256 over ``"<purpose>:<id>:<unsubscribe_token_version>"`` keyed by
``SUBSCRIBER_TOKEN_SECRET``. Properties this buys:

- **Stateless**: nothing stored per link; validation is one indexed pk
  lookup plus a constant-time compare.
- **Purpose-bound**: an unsubscribe token can't drive the preferences
  API and vice versa — the purpose string is inside the MAC.
- **Revocable per-user**: bump ``unsubscribe_token_version`` and every
  outstanding link for that subscriber dies.
- **Revocable globally**: rotate the secret.

The one-shot email *verification* token is different machinery on purpose
(random ``secrets.token_urlsafe`` stored on the row, cleared on use) — it
must be single-use, which stateless tokens can't be.
"""
import hashlib
import hmac

from django.conf import settings

PURPOSE_MANAGE = "manage"
PURPOSE_UNSUBSCRIBE = "unsubscribe"


def _secret() -> bytes:
    # Dedicated secret so it can rotate independently of Django's
    # SECRET_KEY (which would also invalidate sessions); falls back to
    # SECRET_KEY so dev works without another env var.
    return (settings.SUBSCRIBER_TOKEN_SECRET or settings.SECRET_KEY).encode()


def _signature(purpose: str, subscriber_id: int, token_version: int) -> str:
    msg = f"{purpose}:{subscriber_id}:{token_version}".encode()
    return hmac.new(_secret(), msg, hashlib.sha256).hexdigest()


def make_token(subscriber, purpose: str) -> str:
    return f"{subscriber.pk}.{_signature(purpose, subscriber.pk, subscriber.unsubscribe_token_version)}"


def verify_token(token: str, purpose: str):
    """Return the Subscriber the token authenticates, or None."""
    from digests.models import Subscriber

    try:
        raw_id, provided_sig = token.split(".", 1)
        subscriber_id = int(raw_id)
    except (AttributeError, ValueError):
        return None
    subscriber = Subscriber.objects.filter(pk=subscriber_id).first()
    if subscriber is None:
        return None
    expected = _signature(purpose, subscriber.pk, subscriber.unsubscribe_token_version)
    if not hmac.compare_digest(expected, provided_sig):
        return None
    return subscriber
