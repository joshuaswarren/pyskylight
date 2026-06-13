"""Tests for the login flow and Credentials."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx
from httpx import Response

from pyskylight.auth import Credentials, login
from pyskylight.constants import API_PREFIX, DEFAULT_BASE_URL
from pyskylight.errors import SkylightAuthError, SkylightError

URL = f"{DEFAULT_BASE_URL}{API_PREFIX}/sessions"

SESSION_OK = {
    "data": {
        "id": "12677864",
        "type": "authenticated_user",
        "attributes": {"token": "secret-token", "subscription_status": "active"},
    }
}


def test_credentials_basic_header():
    creds = Credentials(user_id="42", token="abc")
    expected = "Basic " + base64.b64encode(b"42:abc").decode()
    assert creds.basic_auth_header == expected


@pytest.mark.parametrize(
    "status,expected",
    [("active", True), ("plus", True), ("trialing", True), ("none", False), (None, False)],
)
def test_is_plus(status, expected):
    assert Credentials("1", "t", subscription_status=status).is_plus is expected


@respx.mock
def test_login_json_success():
    route = respx.post(URL).mock(return_value=Response(200, json=SESSION_OK))
    creds = login("you@example.com", "pw")
    assert creds.user_id == "12677864"
    assert creds.token == "secret-token"
    assert creds.is_plus is True
    # First attempt should be the JSON body.
    sent = route.calls[0].request
    assert b"password" in sent.content
    assert sent.headers["content-type"].startswith("application/json")


@respx.mock
def test_login_bad_credentials_raises_auth_error():
    respx.post(URL).mock(return_value=Response(401, json={"error": "nope"}))
    with pytest.raises(SkylightAuthError):
        login("you@example.com", "wrong")


@respx.mock
def test_login_falls_back_to_form_encoding():
    respx.post(URL).mock(side_effect=[Response(500, text="boom"), Response(200, json=SESSION_OK)])
    creds = login("you@example.com", "pw")
    assert creds.token == "secret-token"


@respx.mock
def test_login_missing_token_raises():
    respx.post(URL).mock(return_value=Response(200, json={"data": {"id": "1", "attributes": {}}}))
    with pytest.raises(SkylightAuthError):
        login("you@example.com", "pw")


@respx.mock
def test_login_network_error():
    respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(SkylightError):
        login("you@example.com", "pw")


@respx.mock
def test_login_prefer_form_first():
    route = respx.post(URL).mock(return_value=Response(200, json=SESSION_OK))
    login("you@example.com", "pw", prefer_json=False)
    # First attempt is form-encoded when prefer_json=False.
    assert b"resettingPassword" in route.calls[0].request.content
