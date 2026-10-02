"""Single-submission scope for durable jobs with ambiguous provider outcomes."""

from contextlib import contextmanager
from contextvars import ContextVar

single_submission = ContextVar("single_job_submission", default=False)


@contextmanager
def job_submission():
    """Keep each recorded attempt to one generation without optional enrichment."""
    token = single_submission.set(True)
    try:
        yield
    finally:
        single_submission.reset(token)
