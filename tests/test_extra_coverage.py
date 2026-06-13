"""Additional tests covering branches not exercised elsewhere."""

from __future__ import annotations

import json

import respx
from httpx import Response
from typer.testing import CliRunner

from pyskylight import Credentials, SkylightClient, cli
from pyskylight.config import Settings, TokenCache
from pyskylight.constants import API_PREFIX, DEFAULT_BASE_URL
from pyskylight.errors import SkylightAuthError, SkylightError
from pyskylight.models import CalendarEvent, Category

runner = CliRunner()


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
    cat = Category.from_jsonapi({"id": "1", "attributes": {"label": "Profile", "color": "#5DB671"}})
    assert cat.label == "Profile"
    assert cat.color == "#5DB671"


# --- client edge cases -----------------------------------------------------
@respx.mock
def test_request_non_json_body_returns_none():
    respx.get(f"{DEFAULT_BASE_URL}{API_PREFIX}/user").mock(
        return_value=Response(200, content=b"plain text")
    )
    client = SkylightClient(Credentials("t"))
    assert client.get_user() == {}


# --- cli._build_client branches -------------------------------------------
def test_build_client_uses_cache():
    TokenCache().save(Credentials("AT"), Settings.from_env().base_url)
    client = cli._build_client(Settings.from_env())
    assert client.credentials.access_token == "AT"


def test_build_client_login_branch(monkeypatch):
    monkeypatch.setenv("SKYLIGHT_EMAIL", "you@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "pw")

    class FakeLoggedIn:
        credentials = Credentials("AT")

    class FakeSky:
        @classmethod
        def login(cls, email, password, base_url):
            return FakeLoggedIn()

    monkeypatch.setattr(cli, "SkylightClient", FakeSky)
    client = cli._build_client(Settings.from_env())
    assert client.credentials.access_token == "AT"


def test_build_client_refreshes_expired_token(monkeypatch):
    # Cached token is expired but has a refresh token -> refresh, not full login.
    TokenCache().save(
        Credentials("OLD", refresh_token="RT", expires_at=1.0), Settings.from_env().base_url
    )
    monkeypatch.setattr(
        cli, "refresh", lambda rt, base_url: Credentials("NEW", refresh_token="RT2")
    )
    client = cli._build_client(Settings.from_env())
    assert client.credentials.access_token == "NEW"


def test_build_client_refresh_failure_falls_back_to_login(monkeypatch):
    TokenCache().save(
        Credentials("OLD", refresh_token="RT", expires_at=1.0), Settings.from_env().base_url
    )
    monkeypatch.setenv("SKYLIGHT_EMAIL", "you@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "pw")

    def boom(rt, base_url):
        raise SkylightError("refresh down")

    monkeypatch.setattr(cli, "refresh", boom)

    class FakeLoggedIn:
        credentials = Credentials("FRESH")

    class FakeSky:
        @classmethod
        def login(cls, email, password, base_url):
            return FakeLoggedIn()

    monkeypatch.setattr(cli, "SkylightClient", FakeSky)
    client = cli._build_client(Settings.from_env())
    assert client.credentials.access_token == "FRESH"


def test_run_auth_error_without_creds(monkeypatch):
    class Boom:
        def get_user(self):
            raise SkylightAuthError("expired")

    monkeypatch.setattr(cli, "_build_client", lambda settings: Boom())
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False
