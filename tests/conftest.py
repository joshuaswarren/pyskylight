"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from pyskylight.auth import Credentials


@pytest.fixture(autouse=True)
def _isolate_env(tmp_path, monkeypatch):
    """Keep tests away from the real cache dir and any SKYLIGHT_* env vars."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    for var in (
        "SKYLIGHT_EMAIL",
        "SKYLIGHT_PASSWORD",
        "SKYLIGHT_BASE_URL",
        "SKYLIGHT_FRAME_ID",
        "SKYLIGHT_TIMEZONE",
    ):
        monkeypatch.delenv(var, raising=False)
    yield


@pytest.fixture
def credentials() -> Credentials:
    return Credentials(user_id="123", token="tok", subscription_status="active")
