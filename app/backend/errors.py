"""The three failure outcomes of a pipeline step (PLAN.md §8.4); search and ask show them as messages."""


class DocError(Exception):
    """This document fails; the user clicks Retry."""


class Paused(Exception):
    """A service is down or the config is wrong: the document stays queued, the worker pauses."""


class RateLimited(Exception):
    """Quota hit: the document waits until retry_at (unix seconds), then resumes by itself."""

    def __init__(self, retry_at: float, reason: str):
        super().__init__(reason)
        self.retry_at = retry_at
        self.reason = reason
