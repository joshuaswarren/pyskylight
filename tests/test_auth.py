"""Tests for the OAuth2 PKCE login flow and Credentials."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from httpx import Response

from pyskylight.auth import Credentials, login, refresh
from pyskylight.constants import DEFAULT_BASE_URL
from pyskylight.errors import SkylightAuthError, SkylightError

B = DEFAULT_BASE_URL
TOKEN_OK = {
    "access_token": "AT",
    "refresh_token": "RT",
    "expires_in": 7200,
    "created_at": 1000,
    "token_type": "Bearer",
    "scope": "everything",
}


def _setup_oauth(
    *, csrf="csrf123", good_creds=True, wrong_state=False, token_status=200, token_body=None
):
    """Wire up the three OAuth endpoints on the active respx router."""
    holder = {}

    def on_authorize(request):
        holder["state"] = parse_qs(urlparse(str(request.url)).query).get("state", [""])[0]
        body = "<form>no token here</form>"
        if csrf:
            body = f'<form><input type="hidden" name="authenticity_token" value="{csrf}"></form>'
        return Response(200, html=body)

    def on_session(request):
        if not good_creds:
            return Response(200, html="login failed, try again")  # no redirect -> bad creds
        state = "WRONG" if wrong_state else holder["state"]
        return Response(
            302, headers={"Location": f"skylight-family://welcome?code=AUTHCODE&state={state}"}
        )

    respx.get(B + "/oauth/authorize").mock(side_effect=on_authorize)
    respx.post(B + "/auth/session").mock(side_effect=on_session)
    respx.post(B + "/oauth/token").mock(
        return_value=Response(token_status, json=token_body if token_body is not None else TOKEN_OK)
    )
    return holder


def test_credentials_bearer_header():
    assert Credentials("AT").bearer_header == "Bearer AT"


def test_is_expired():
    assert Credentials("AT", expires_at=1000).is_expired(2000) is True
    assert Credentials("AT", expires_at=1000).is_expired(500) is False
    assert Credentials("AT").is_expired(9_999_999) is False  # unknown expiry -> not expired


@respx.mock
def test_login_success():
    _setup_oauth()
    creds = login("you@example.com", "pw")
    assert creds.access_token == "AT"
    assert creds.refresh_token == "RT"
    assert creds.expires_at == 1000 + 7200


@respx.mock
def test_login_bad_credentials():
    _setup_oauth(good_creds=False)
    with pytest.raises(SkylightAuthError):
        login("you@example.com", "wrong")


@respx.mock
def test_login_no_csrf():
    _setup_oauth(csrf="")
    with pytest.raises(SkylightAuthError):
        login("you@example.com", "pw")


@respx.mock
def test_login_state_mismatch():
    _setup_oauth(wrong_state=True)
    with pytest.raises(SkylightAuthError):
        login("you@example.com", "pw")


@respx.mock
def test_login_token_exchange_fails():
    _setup_oauth(token_status=400, token_body={"error": "invalid_grant"})
    with pytest.raises(SkylightAuthError):
        login("you@example.com", "pw")


@respx.mock
def test_login_no_access_token():
    _setup_oauth(token_body={"token_type": "Bearer"})
    with pytest.raises(SkylightAuthError):
        login("you@example.com", "pw")


@respx.mock
def test_login_network_error():
    respx.get(B + "/oauth/authorize").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(SkylightError):
        login("you@example.com", "pw")


@respx.mock
def test_refresh_success():
    respx.post(B + "/oauth/token").mock(return_value=Response(200, json=TOKEN_OK))
    creds = refresh("RT")
    assert creds.access_token == "AT"


@respx.mock
def test_refresh_failure():
    respx.post(B + "/oauth/token").mock(return_value=Response(401, json={"error": "bad"}))
    with pytest.raises(SkylightAuthError):
        refresh("RT")


@respx.mock
def test_refresh_network_error():
    respx.post(B + "/oauth/token").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(SkylightError):
        refresh("RT")
