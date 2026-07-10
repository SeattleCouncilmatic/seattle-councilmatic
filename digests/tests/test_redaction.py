import logging

from django.test import SimpleTestCase

from seattle_app.logging_filters import EmailRedactionFilter


def _record(msg, args=None):
    return logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=None,
    )


class EmailRedactionFilterTests(SimpleTestCase):
    def setUp(self):
        self.filter = EmailRedactionFilter()

    def test_masks_email_in_message(self):
        record = _record("delivery failed for person@example.org today")
        self.filter.filter(record)
        self.assertNotIn("person@example.org", record.getMessage())
        self.assertIn("«email»", record.getMessage())

    def test_masks_email_passed_as_format_arg(self):
        record = _record("delivery failed for %s", ("person@example.org",))
        self.filter.filter(record)
        self.assertNotIn("person@example.org", record.getMessage())

    def test_masks_multiple_emails(self):
        record = _record("cc a@x.org and b@y.co.uk")
        self.filter.filter(record)
        message = record.getMessage()
        self.assertNotIn("a@x.org", message)
        self.assertNotIn("b@y.co.uk", message)

    def test_leaves_plain_lines_untouched(self):
        record = _record("processed 12 items in 3.4s")
        self.filter.filter(record)
        self.assertEqual(record.getMessage(), "processed 12 items in 3.4s")

    def test_decorator_syntax_not_masked(self):
        # Python decorators aren't emails — but over-masking would be
        # acceptable; this documents current behavior (no domain dot → no match).
        record = _record("applied @csrf_exempt to view")
        self.filter.filter(record)
        self.assertIn("csrf_exempt", record.getMessage())

    def test_masks_email_inside_exception_traceback(self):
        # Regression: SMTPRecipientsRefused embeds the recipient address in
        # its message, which reaches the log via exc_info → formatted
        # traceback, not via the log message. Caught live on the first
        # dev-SMTP smoke test.
        import sys

        try:
            raise ValueError("refused: {'leak@example.org': (550, b'rejected')}")
        except ValueError:
            record = _record("Verification email send failed for subscriber 7")
            record.exc_info = sys.exc_info()

        self.filter.filter(record)
        formatted = logging.Formatter().format(record)
        self.assertNotIn("leak@example.org", formatted)
        self.assertIn("«email»", formatted)
        self.assertIn("ValueError", formatted)  # traceback itself survives
