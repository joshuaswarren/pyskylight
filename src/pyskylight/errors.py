"""Exception hierarchy for pyskylight.

All errors raised by the client derive from :class:`SkylightError`, so callers can
catch a single base type. More specific subclasses map to common HTTP outcomes so
callers (and the CLI) can react precisely — e.g. re-login on auth failure, back off
on rate limiting, or surface the Skylight Plus gate clearly.
"""

from __future__ import annotations

from typing import Optional


class SkylightError(Exception):
    """Base class for every error raised by pyskylight."""


class SkylightAuthError(SkylightError):
    """Authentication failed or the session token is invalid/expired (HTTP 401).

    On this error the caller should re-run the login flow and retry once.
    """


class SkylightPlusRequiredError(SkylightError):
    """The endpoint requires an active Skylight Plus subscription (HTTP 403).

    The Meals / Recipes / Rewards features are gated behind Skylight Plus; without
    it those endpoints reject the request even with valid credentials.
    """


class SkylightNotFoundError(SkylightError):
    """The requested resource does not exist (HTTP 404)."""


class SkylightRateLimitError(SkylightError):
    """The API is rate-limiting the client (HTTP 429).

    ``retry_after`` carries the server's ``Retry-After`` value in seconds when the
    header was present, so callers can honor the requested back-off.
    """

    def __init__(self, message: str, retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SkylightAPIError(SkylightError):
    """Any other non-success response from the API.

    ``status_code`` and ``body`` are captured to aid debugging without leaking them
    into logs automatically.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
