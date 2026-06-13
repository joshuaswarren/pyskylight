"""Skylight legacy email/password login.

The default, best-supported authentication flow:

1. ``POST /api/sessions`` with ``{email, password}``.
2. The response is JSON:API; ``data.id`` is the numeric **user id** and
   ``data.attributes.token`` is the **session token** (plus, usually,
   ``subscription_status``).
3. Every subsequent request sends ``Authorization: Basic base64(user_id:token)``.

We try a JSON body first (cleanest), then fall back to a form-encoded body with the
extra fields the official web client sends, since some deployments only accept that.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx

from .constants import API_PREFIX, DEFAULT_BASE_URL, DEFAULT_TIMEOUT, USER_AGENT
from .errors import SkylightAuthError, SkylightError

# Extra fields the official web client posts alongside email/password.
_FORM_EXTRAS = {
    "resettingPassword": "false",
    "textMeTheApp": "false",
    "agreedToMarketing": "false",
}


@dataclass
class Credentials:
    """A logged-in Skylight session."""

    user_id: str
    token: str
    subscription_status: Optional[str] = None

    @property
    def is_plus(self) -> bool:
        """Best-effort check for an active Skylight Plus subscription."""
        status = (self.subscription_status or "").lower()
        return status in {"active", "plus", "trialing", "subscribed"}

    @property
    def basic_auth_header(self) -> str:
        """The ``Authorization`` header value for authenticated requests."""
        raw = f"{self.user_id}:{self.token}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")


def _parse_session(payload: Dict[str, Any]) -> Credentials:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise SkylightAuthError("Unexpected login response: missing 'data' object")
    user_id = data.get("id")
    attributes = data.get("attributes") or {}
    token = attributes.get("token")
    if not user_id or not token:
        raise SkylightAuthError("Login response did not contain a user id and token")
    return Credentials(
        user_id=str(user_id),
        token=str(token),
        subscription_status=attributes.get("subscription_status"),
    )


def login(
    email: str,
    password: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    http: Optional[httpx.Client] = None,
    prefer_json: bool = True,
    timeout: float = DEFAULT_TIMEOUT,
) -> Credentials:
    """Log in and return :class:`Credentials`.

    Raises :class:`SkylightAuthError` on bad credentials or an unexpected response.
    """
    url = f"{base_url}{API_PREFIX}/sessions"
    owns_client = http is None
    client = http or httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT})
    try:
        attempts = []
        if prefer_json:
            attempts.append(("json", {"email": email, "password": password}))
            attempts.append(("data", {"email": email, "password": password, **_FORM_EXTRAS}))
        else:
            attempts.append(("data", {"email": email, "password": password, **_FORM_EXTRAS}))
            attempts.append(("json", {"email": email, "password": password}))

        last_error: Optional[Exception] = None
        for kind, body in attempts:
            try:
                if kind == "json":
                    resp = client.post(url, json=body, headers={"Accept": "application/json"})
                else:
                    resp = client.post(url, data=body, headers={"Accept": "application/json"})
            except httpx.HTTPError as exc:  # network-level failure
                raise SkylightError(f"Network error during login: {exc}") from exc

            if resp.status_code == 401:
                raise SkylightAuthError("Invalid Skylight email or password")
            if resp.is_success:
                try:
                    return _parse_session(resp.json())
                except ValueError as exc:
                    last_error = SkylightAuthError(f"Login response was not valid JSON: {exc}")
                    continue
            # Non-success, non-401: remember and try the next body shape.
            last_error = SkylightAuthError(f"Login failed with HTTP {resp.status_code}")
        raise last_error or SkylightAuthError("Login failed")
    finally:
        if owns_client:
            client.close()
