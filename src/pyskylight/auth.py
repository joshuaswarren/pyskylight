"""Skylight OAuth2 (PKCE) login.

The legacy ``/api/sessions`` email/password endpoint is version-gated and effectively
retired (it rejects every client version it recognizes). The flow the current apps use
is OAuth2 Authorization-Code + PKCE:

1. ``GET /oauth/authorize`` -> the web login page (carries a CSRF ``authenticity_token``).
2. ``POST /auth/session`` with ``{authenticity_token, email, password}`` -> on success
   the server redirects (following a couple of hops) to
   ``skylight-family://welcome?code=...&state=...``.
3. ``POST /oauth/token`` with the code + PKCE ``code_verifier`` -> ``access_token``
   (+ ``refresh_token``).

Data requests then send ``Authorization: Bearer <access_token>``.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx

from .constants import (
    BROWSER_UA,
    DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    OAUTH_CLIENT_ID,
    OAUTH_CODE_CHALLENGE_METHOD,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPE,
)
from .errors import SkylightAuthError, SkylightError

_CSRF_RE = re.compile(r'name="authenticity_token"[^>]*value="([^"]+)"')
_REDIRECT_CODES = (301, 302, 303, 307, 308)


@dataclass
class Credentials:
    """A logged-in Skylight session (OAuth2 Bearer)."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None  # epoch seconds (created_at + expires_in)

    @property
    def bearer_header(self) -> str:
        return "Bearer " + self.access_token

    def is_expired(self, now: float, leeway: float = 60.0) -> bool:
        """True if the access token has expired (with a small leeway)."""
        return self.expires_at is not None and now >= (self.expires_at - leeway)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _credentials_from_token(payload: Dict[str, Any]) -> Credentials:
    access = payload.get("access_token")
    if not access:
        raise SkylightAuthError("Token response did not contain an access_token")
    created = payload.get("created_at")
    expires_in = payload.get("expires_in")
    expires_at: Optional[float] = None
    if isinstance(created, (int, float)) and isinstance(expires_in, (int, float)):
        expires_at = float(created) + float(expires_in)
    refresh = payload.get("refresh_token")
    return Credentials(
        access_token=str(access),
        refresh_token=str(refresh) if refresh else None,
        expires_at=expires_at,
    )


def _get_no_redirect(client: httpx.Client, url: str) -> httpx.Response:
    return client.get(url, headers={"User-Agent": BROWSER_UA}, follow_redirects=False)


def _follow_to_form(client: httpx.Client, resp: httpx.Response, base_url: str) -> httpx.Response:
    """Follow redirects from /oauth/authorize until the login form (or stop)."""
    hops = 0
    while resp.status_code in _REDIRECT_CODES and resp.headers.get("location") and hops < 10:
        loc = resp.headers["location"]
        if loc.startswith("skylight-family:"):
            break
        resp = _get_no_redirect(client, loc if loc.startswith("http") else base_url + loc)
        hops += 1
    return resp


def _chase_to_redirect(client: httpx.Client, resp: httpx.Response, base_url: str) -> Optional[str]:
    """After the login POST, follow redirects until the ``skylight-family:`` location."""
    loc = resp.headers.get("location")
    hops = 0
    while loc and not loc.startswith("skylight-family:") and hops < 8:
        resp = _get_no_redirect(client, loc if loc.startswith("http") else base_url + loc)
        loc = resp.headers.get("location")
        hops += 1
    return loc


def login(
    email: str,
    password: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    http: Optional[httpx.Client] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Credentials:
    """Log in via OAuth2 PKCE and return :class:`Credentials`.

    Raises :class:`SkylightAuthError` on bad credentials or an unexpected response.
    """
    base_url = base_url.rstrip("/")
    owns_client = http is None
    client = http or httpx.Client(timeout=timeout)
    try:
        verifier = _b64url(secrets.token_bytes(32))
        challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
        state = _b64url(secrets.token_bytes(18))
        params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": OAUTH_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": OAUTH_CODE_CHALLENGE_METHOD,
            "prompt": "login",
        }
        try:
            resp = client.get(
                base_url + "/oauth/authorize",
                params=params,
                headers={"User-Agent": BROWSER_UA},
                follow_redirects=False,
            )
            resp = _follow_to_form(client, resp, base_url)
            csrf = _CSRF_RE.search(resp.text)
            if not csrf:
                raise SkylightAuthError("Could not load the Skylight login form (no CSRF token)")

            resp = client.post(
                base_url + "/auth/session",
                data={"authenticity_token": csrf.group(1), "email": email, "password": password},
                headers={"User-Agent": BROWSER_UA},
                follow_redirects=False,
            )
            location = _chase_to_redirect(client, resp, base_url)
            if not (location and location.startswith("skylight-family:")):
                raise SkylightAuthError("Invalid Skylight email or password")
            query = parse_qs(urlparse(location).query)
            returned_state = query.get("state", [""])[0] if query.get("state") else ""
            if returned_state != state:
                raise SkylightAuthError("OAuth state mismatch")
            code_values = query.get("code") or []
            code = code_values[0] if code_values else ""
            if not code:
                raise SkylightAuthError("OAuth authorization code missing")

            token_resp = client.post(
                base_url + "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": OAUTH_CLIENT_ID,
                    "code": code,
                    "redirect_uri": OAUTH_REDIRECT_URI,
                    "code_verifier": verifier,
                },
                headers={"User-Agent": BROWSER_UA},
            )
        except httpx.HTTPError as exc:
            raise SkylightError(f"Network error during login: {exc}") from exc

        if token_resp.status_code >= 400:
            raise SkylightAuthError(f"Token exchange failed (HTTP {token_resp.status_code})")
        try:
            return _credentials_from_token(token_resp.json())
        except ValueError as exc:
            raise SkylightAuthError(f"Token response was not valid JSON: {exc}") from exc
    finally:
        if owns_client:
            client.close()


def refresh(
    refresh_token: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
    http: Optional[httpx.Client] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Credentials:
    """Exchange a refresh token for a fresh access token."""
    base_url = base_url.rstrip("/")
    owns_client = http is None
    client = http or httpx.Client(timeout=timeout)
    try:
        try:
            token_resp = client.post(
                base_url + "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": OAUTH_CLIENT_ID,
                    "refresh_token": refresh_token,
                },
                headers={"User-Agent": BROWSER_UA},
            )
        except httpx.HTTPError as exc:
            raise SkylightError(f"Network error during token refresh: {exc}") from exc
        if token_resp.status_code >= 400:
            raise SkylightAuthError(f"Token refresh failed (HTTP {token_resp.status_code})")
        try:
            return _credentials_from_token(token_resp.json())
        except ValueError as exc:
            raise SkylightAuthError(f"Refresh response was not valid JSON: {exc}") from exc
    finally:
        if owns_client:
            client.close()
