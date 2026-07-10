"""Logging filter that stamps the current pipeline ``run_key`` onto log records.

Kept in its own module with **no model imports**: Django applies ``LOGGING`` via
``dictConfig`` during ``django.setup()``, *before* the app registry is populated,
so a filter whose module imported models would raise ``AppRegistryNotReady`` at
startup. The batch pipeline sets ``run_key_var``; the filter copies it onto each
record so a formatter can render ``[%(run_key)s]``. (#205 / #208)
"""
import contextvars
import logging
import re
import traceback

# Correlation id for the current pipeline run. Defaults to "-" outside a run.
run_key_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pipeline_run_key", default="-"
)


class PipelineRunKeyFilter(logging.Filter):
    """Inject the current ``run_key`` onto every record so a formatter can
    prefix ``[%(run_key)s]``."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.run_key = run_key_var.get()
        return True


# Deliberately permissive local-part/domain match — over-masking a
# false positive costs a slightly garbled log line; under-masking leaks
# subscriber PII (#231).
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_MASK = "«email»"


def redact_emails(text: str) -> str:
    """Mask email-shaped substrings in ``text``. For non-log surfaces that
    persist exception text — e.g. ``DigestSend.error``, which renders in the
    admin and must never hold a recipient address."""
    return _EMAIL_RE.sub(_MASK, text or "")


class EmailRedactionFilter(logging.Filter):
    """Mask anything email-shaped before it reaches a handler. Digest code
    logs ``subscriber.id`` on purpose; this is the backstop for library
    log lines (SMTP errors, request logging) that might echo an address."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        # getMessage() interpolates args into msg, so redact the combined
        # string and drop args — redacting msg alone would miss an email
        # passed as a %s argument.
        try:
            message = record.getMessage()
        except Exception:
            return True
        if "@" in message:
            record.msg = _EMAIL_RE.sub(_MASK, message)
            record.args = None
        # Tracebacks leak addresses too — e.g. SMTPRecipientsRefused's
        # message embeds the recipient. Formatters cache the rendered
        # traceback on exc_text (and skip re-rendering exc_info when it's
        # set), so pre-render here and redact the cached copy.
        if record.exc_info and not record.exc_text:
            record.exc_text = "".join(
                traceback.format_exception(*record.exc_info)
            ).rstrip("\n")
        if record.exc_text and "@" in record.exc_text:
            record.exc_text = _EMAIL_RE.sub(_MASK, record.exc_text)
        return True
