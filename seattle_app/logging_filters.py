"""Logging filter that stamps the current pipeline ``run_key`` onto log records.

Kept in its own module with **no model imports**: Django applies ``LOGGING`` via
``dictConfig`` during ``django.setup()``, *before* the app registry is populated,
so a filter whose module imported models would raise ``AppRegistryNotReady`` at
startup. The batch pipeline sets ``run_key_var``; the filter copies it onto each
record so a formatter can render ``[%(run_key)s]``. (#205 / #208)
"""
import contextvars
import logging

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
