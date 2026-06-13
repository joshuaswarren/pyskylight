"""Tests for the ``skylight`` CLI."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from pyskylight import cli
from pyskylight.auth import Credentials
from pyskylight.errors import SkylightAuthError, SkylightPlusRequiredError
from pyskylight.models import Frame, MealCategory, Recipe, Sitting

runner = CliRunner()


class FakeClient:
    """A stand-in for SkylightClient used by CLI tests."""

    def __init__(self, **overrides):
        self.credentials = Credentials(access_token="AT", refresh_token="RT", expires_at=None)
        self._overrides = overrides
        self.calls = []

    def _maybe(self, name, default):
        if name in self._overrides:
            return self._overrides[name]
        return default

    def get_user(self):
        self.calls.append("get_user")
        val = self._maybe("get_user", {"data": {"id": "123"}})
        if isinstance(val, Exception):
            raise val
        return val

    def list_frames(self, include_deleted=False):
        if "list_frames" in self._overrides and isinstance(
            self._overrides["list_frames"], Exception
        ):
            raise self._overrides["list_frames"]
        return [Frame.from_jsonapi({"id": "7", "type": "frame", "attributes": {"name": "Home"}})]

    def get_frame(self, frame_id):
        return Frame.from_jsonapi({"id": frame_id, "type": "frame", "attributes": {"name": "Home"}})

    def list_calendar_events(self, *a, **k):
        return []

    def list_categories(self, frame_id):
        return []

    def list_meal_categories(self, frame_id):
        return [MealCategory.from_jsonapi({"id": "1", "attributes": {"label": "Dinner"}})]

    def list_recipes(self, frame_id, include="meal_category"):
        return [Recipe.from_jsonapi({"id": "9", "attributes": {"summary": "Tacos"}})]

    def get_recipe(self, frame_id, recipe_id):
        return Recipe.from_jsonapi({"id": recipe_id, "attributes": {"summary": "Tacos"}})

    def create_recipe(self, frame_id, summary, description=None, meal_category_id=None):
        return Recipe.from_jsonapi({"id": "10", "attributes": {"summary": summary}})

    def delete_recipe(self, frame_id, recipe_id):
        return None

    def list_sittings(self, frame_id, date_min=None, date_max=None):
        return [Sitting.from_jsonapi({"id": "1", "attributes": {"date": "2026-06-20"}})]

    def create_sitting(self, frame_id, date, meal_category_id, meal_recipe_id=None):
        return Sitting.from_jsonapi({"id": "2", "attributes": {"date": date}})

    def list_lists(self, frame_id):
        return [{"id": "1"}]

    def list_chores(self, frame_id):
        return [{"id": "1"}]


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(cli, "_build_client", lambda settings: client)
    return client


def test_login_command(monkeypatch):
    monkeypatch.setenv("SKYLIGHT_EMAIL", "you@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "pw")

    class FakeSky:
        @classmethod
        def login(cls, email, password, base_url):
            return FakeClient()

    monkeypatch.setattr(cli, "SkylightClient", FakeSky)
    result = runner.invoke(cli.app, ["login"])
    assert result.exit_code == 0
    out = json.loads(result.stdout)
    assert out["ok"] is True
    assert out["is_plus"] is False  # FakeClient.get_user has no subscription_status


def test_login_requires_env():
    result = runner.invoke(cli.app, ["login"])
    assert result.exit_code != 0


def test_logout():
    result = runner.invoke(cli.app, ["logout"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["ok"] is True


def test_whoami(fake_client):
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["id"] == "123"


def test_frames(fake_client):
    result = runner.invoke(cli.app, ["frames"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data[0]["id"] == "7"


def test_frame(fake_client):
    result = runner.invoke(cli.app, ["frame", "7"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["id"] == "7"


def test_recipes_with_frame_flag(fake_client):
    result = runner.invoke(cli.app, ["recipes", "--frame", "7"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["attributes"]["summary"] == "Tacos"


def test_recipes_uses_env_frame(monkeypatch, fake_client):
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    result = runner.invoke(cli.app, ["recipes"])
    assert result.exit_code == 0


def test_recipes_missing_frame_errors(fake_client):
    result = runner.invoke(cli.app, ["recipes"])
    assert result.exit_code != 0


def test_meal_categories(monkeypatch, fake_client):
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    result = runner.invoke(cli.app, ["meal-categories"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)[0]["attributes"]["label"] == "Dinner"


def test_create_recipe(monkeypatch, fake_client):
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    result = runner.invoke(cli.app, ["create-recipe", "--summary", "Tacos"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["attributes"]["summary"] == "Tacos"


def test_delete_recipe(monkeypatch, fake_client):
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    result = runner.invoke(cli.app, ["delete-recipe", "9"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["deleted"] == "9"


def test_plan_and_add(monkeypatch, fake_client):
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    assert runner.invoke(cli.app, ["plan"]).exit_code == 0
    result = runner.invoke(
        cli.app, ["plan-add", "--date", "2026-06-20", "--meal-category-id", "3", "--recipe-id", "9"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["attributes"]["date"] == "2026-06-20"


def test_events_requires_timezone(monkeypatch, fake_client):
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    result = runner.invoke(cli.app, ["events", "--from", "a", "--to", "b"])
    assert result.exit_code != 0


def test_events_ok(monkeypatch, fake_client):
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    monkeypatch.setenv("SKYLIGHT_TIMEZONE", "America/Chicago")
    result = runner.invoke(cli.app, ["events", "--from", "a", "--to", "b"])
    assert result.exit_code == 0


def test_categories_lists_chores(monkeypatch, fake_client):
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    assert runner.invoke(cli.app, ["categories"]).exit_code == 0
    assert runner.invoke(cli.app, ["lists"]).exit_code == 0
    assert runner.invoke(cli.app, ["chores"]).exit_code == 0


def test_error_path_prints_json(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_build_client",
        lambda settings: FakeClient(list_frames=SkylightPlusRequiredError("plus")),
    )
    result = runner.invoke(cli.app, ["frames"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["ok"] is False


def test_auth_retry(monkeypatch):
    monkeypatch.setenv("SKYLIGHT_EMAIL", "you@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "pw")
    first = FakeClient(get_user=SkylightAuthError("expired"))
    second = FakeClient()
    monkeypatch.setattr(cli, "_build_client", lambda settings: first)

    class FakeSky:
        @classmethod
        def login(cls, email, password, base_url):
            return second

    monkeypatch.setattr(cli, "SkylightClient", FakeSky)
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["data"]["id"] == "123"


def test_build_client_no_creds_raises(monkeypatch):
    # No cache, no env creds -> BadParameter inside _build_client.
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code != 0
