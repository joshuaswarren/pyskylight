"""Additional tests covering branches not exercised elsewhere."""

from __future__ import annotations

import json

import respx
from httpx import Response
from typer.testing import CliRunner

from pyskylight import Credentials, SkylightClient, cli
from pyskylight.auth import login
from pyskylight.config import Settings, TokenCache
from pyskylight.constants import API_PREFIX, DEFAULT_BASE_URL
from pyskylight.errors import SkylightAuthError
from pyskylight.models import CalendarEvent, Category

runner = CliRunner()
URL = f"{DEFAULT_BASE_URL}{API_PREFIX}/sessions"


# --- models ----------------------------------------------------------------
def test_calendar_event_properties():
    ev = CalendarEvent.from_jsonapi(
        {
            "id": "1",
            "attributes": {
                "summary": "Dentist",
                "starts_at": "2026-06-20T09:00:00",
                "ends_at": "2026-06-20T10:00:00",
                "all_day": True,
            },
        }
    )
    assert ev.summary == "Dentist"
    assert ev.starts_at.startswith("2026-06-20")
    assert ev.ends_at.endswith("10:00:00")
    assert ev.all_day is True


def test_category_properties():
    cat = Category.from_jsonapi({"id": "1", "attributes": {"label": "Luke", "color": "#5DB671"}})
    assert cat.label == "Luke"
    assert cat.color == "#5DB671"


# --- auth edge cases -------------------------------------------------------
@respx.mock
def test_login_data_not_dict():
    respx.post(URL).mock(return_value=Response(200, json={"data": "nope"}))
    try:
        login("a@b.com", "pw")
        assert False, "expected SkylightAuthError"
    except SkylightAuthError:
        pass


@respx.mock
def test_login_invalid_json_then_ok():
    respx.post(URL).mock(
        side_effect=[
            Response(200, text="not-json"),
            Response(200, json={"data": {"id": "1", "attributes": {"token": "t"}}}),
        ]
    )
    creds = login("a@b.com", "pw")
    assert creds.token == "t"


@respx.mock
def test_login_all_attempts_fail():
    respx.post(URL).mock(side_effect=[Response(500), Response(503)])
    try:
        login("a@b.com", "pw")
        assert False, "expected SkylightAuthError"
    except SkylightAuthError:
        pass


# --- client edge cases -----------------------------------------------------
@respx.mock
def test_request_non_json_body_returns_none():
    respx.get(f"{DEFAULT_BASE_URL}{API_PREFIX}/user").mock(
        return_value=Response(200, content=b"plain text")
    )
    client = SkylightClient(Credentials("1", "t"))
    assert client.get_user() == {}


# --- cli._build_client branches -------------------------------------------
def test_build_client_uses_cache():
    TokenCache().save(Credentials("1", "tok"), Settings.from_env().base_url)
    client = cli._build_client(Settings.from_env())
    assert client.credentials.user_id == "1"


def test_build_client_login_branch(monkeypatch):
    monkeypatch.setenv("SKYLIGHT_EMAIL", "you@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "pw")

    class FakeLoggedIn:
        credentials = Credentials("1", "t")

    class FakeSky:
        @classmethod
        def login(cls, email, password, base_url):
            return FakeLoggedIn()

    monkeypatch.setattr(cli, "SkylightClient", FakeSky)
    client = cli._build_client(Settings.from_env())
    assert client.credentials.user_id == "1"


def test_run_auth_error_without_creds(monkeypatch):
    class Boom:
        def get_user(self):
            raise SkylightAuthError("expired")

    monkeypatch.setattr(cli, "_build_client", lambda settings: Boom())
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
