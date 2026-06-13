"""Tests for settings, secret resolution and token caching."""

from __future__ import annotations

import subprocess

import pytest

from pyskylight import config
from pyskylight.auth import Credentials
from pyskylight.config import Settings, TokenCache, resolve_secret
from pyskylight.errors import SkylightError


def test_resolve_secret_plain_passthrough():
    assert resolve_secret("plain") == "plain"
    assert resolve_secret(None) is None


def test_resolve_secret_op_reference(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd == ["op", "read", "op://Shared/Skylight/password"]
        return subprocess.CompletedProcess(cmd, 0, stdout="s3cret\n", stderr="")

    monkeypatch.setattr(config.subprocess, "run", fake_run)
    assert resolve_secret("op://Shared/Skylight/password") == "s3cret"


def test_resolve_secret_op_missing_cli(monkeypatch):
    def boom(cmd, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(config.subprocess, "run", boom)
    with pytest.raises(SkylightError):
        resolve_secret("op://a/b/c")


def test_resolve_secret_op_failure(monkeypatch):
    def boom(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="bad ref")

    monkeypatch.setattr(config.subprocess, "run", boom)
    with pytest.raises(SkylightError):
        resolve_secret("op://a/b/c")


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("SKYLIGHT_EMAIL", "you@example.com")
    monkeypatch.setenv("SKYLIGHT_PASSWORD", "pw")
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "55")
    monkeypatch.setenv("SKYLIGHT_TIMEZONE", "America/Chicago")
    monkeypatch.setenv("SKYLIGHT_BASE_URL", "https://example.test/")
    s = Settings.from_env()
    assert s.email == "you@example.com"
    assert s.frame_id == "55"
    assert s.timezone == "America/Chicago"
    assert s.base_url == "https://example.test"  # trailing slash stripped


def test_token_cache_roundtrip(tmp_path):
    cache = TokenCache(path=tmp_path / "token.json")
    creds = Credentials("1", "tok", "active")
    cache.save(creds, "https://app.ourskylight.com")
    loaded = cache.load("https://app.ourskylight.com")
    assert loaded is not None
    assert loaded.user_id == "1"
    assert loaded.token == "tok"
    assert loaded.subscription_status == "active"
    # owner-only perms
    assert oct(cache.path.stat().st_mode & 0o777) == "0o600"


def test_token_cache_base_url_mismatch(tmp_path):
    cache = TokenCache(path=tmp_path / "token.json")
    cache.save(Credentials("1", "tok"), "https://a")
    assert cache.load("https://b") is None


def test_token_cache_missing_and_corrupt(tmp_path):
    cache = TokenCache(path=tmp_path / "nope.json")
    assert cache.load("https://a") is None
    cache.path.write_text("{not json", encoding="utf-8")
    assert cache.load("https://a") is None


def test_token_cache_missing_fields(tmp_path):
    cache = TokenCache(path=tmp_path / "t.json")
    cache.path.write_text('{"base_url": "https://a", "user_id": "1"}', encoding="utf-8")
    assert cache.load("https://a") is None


def test_token_cache_clear(tmp_path):
    cache = TokenCache(path=tmp_path / "t.json")
    cache.save(Credentials("1", "tok"), "https://a")
    cache.clear()
    assert not cache.path.exists()
    cache.clear()  # idempotent
