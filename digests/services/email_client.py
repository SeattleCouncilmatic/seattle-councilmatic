"""``DigestEmailClient`` — the single interface all outbound digest mail
goes through (#231).

Two planned implementations, selected by ``DIGEST_EMAIL_BACKEND``:

- ``smtp`` (this file, the Phase 1-3 default): Django's mail machinery on
  the same ``EMAIL_*`` config the pipeline-health alerts use. **Test-to-self
  only, never real subscribers** — Gmail-class relays aren't bulk senders,
  cap daily volume, and provide no bounce/complaint handling.
- ``postmark`` (Phase 4): the production transport. Wired last so the
  content phases can ship real email to your own inbox before any Postmark
  account, domain warmup, or DMARC work exists.

Mirrors the ``DigestLLMClient`` pattern: callers depend on the interface,
only the transport differs.
"""
from dataclasses import dataclass, field

from django.conf import settings
from django.core.mail import EmailMultiAlternatives


@dataclass
class SendResult:
    """Outcome of one send. ``provider_message_id`` is Postmark's MessageID
    once that transport exists; the SMTP backend has no equivalent, so it
    stays empty and ``DigestSend.postmark_message_id`` stays null-ish."""

    provider_message_id: str = ""
    headers: dict = field(default_factory=dict)


class DigestEmailClient:
    """Interface. Implementations raise on failure — callers decide whether
    a failure flips subscriber status (digest sends do; a verification
    resend doesn't)."""

    def send(self, *, to: str, subject: str, text_body: str,
             html_body: str | None = None, headers: dict | None = None) -> SendResult:
        raise NotImplementedError


class SmtpDigestEmailClient(DigestEmailClient):
    def send(self, *, to, subject, text_body, html_body=None, headers=None) -> SendResult:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=settings.DIGEST_FROM_EMAIL,
            to=[to],
            headers=headers or {},
        )
        if html_body:
            message.attach_alternative(html_body, "text/html")
        message.send(fail_silently=False)
        return SendResult()


def get_email_client() -> DigestEmailClient:
    backend = settings.DIGEST_EMAIL_BACKEND
    if backend == "smtp":
        return SmtpDigestEmailClient()
    if backend == "postmark":
        raise NotImplementedError(
            "The Postmark transport lands in Phase 4 (see digests plan); "
            "run with DIGEST_EMAIL_BACKEND=smtp until then."
        )
    raise ValueError(f"Unknown DIGEST_EMAIL_BACKEND {backend!r} (expected 'smtp' or 'postmark').")
