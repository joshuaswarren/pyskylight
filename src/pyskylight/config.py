"""Configuration, secret resolution and token caching for the CLI.

Credentials come from environment variables (which may themselves be ``op://``
references resolved via the 1Password CLI). A short-lived token cache avoids logging
in on every CLI invocation.

Environment variables:
  SKYLIGHT_EMAIL       account email (or an ``op://`` reference)
  SKYLIGHT_PASSWORD    account password (or an ``op://`` reference)
  SKYLIGHT_BASE_URL    override the API base URL (default app.ourskylight.com)
  SKYLIGHT_FRAME_ID    default frame/household id, so ``--frame`` is optional
  SKYLIGHT_TIMEZONE    default IANA timezone for calendar queries
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from .auth import Credentials
from .constants import DEFAULT_BASE_URL
from .errors import SkylightError


def resolve_secret(value: Optional[str]) -> Optional[str]:
    """Resolve a value, dereferencing ``op://`` 1Password references via ``op read``.

    Plain values are returned unchanged. This keeps real secrets out of the
    environment/process list when the user stores ``op://vault/item/field`` instead.
    """
    if not value or not value.startswith("op://"):
        return value
    try:
        result = subprocess.run(
            ["op", "read", value],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise SkylightError("1Password CLI ('op') not found but an op:// secret was used") from exc
    except subprocess.CalledProcessError as exc:
        raise SkylightError(
            f"Failed to resolve secret via 'op read': {exc.stderr.strip()}"
        ) from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - environment dependent
        raise SkylightError("Timed out resolving secret via 'op read'") from exc
    return result.stdout.strip()


@dataclass
class Settings:
    """Resolved CLI settings."""

    email: Optional[str] = None
    password: Optional[str] = None
    base_url: str = DEFAULT_BASE_URL
    frame_id: Optional[str] = None
    timezone: Optional[str] = None

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        source: Mapping[str, str] = env if env is not None else os.environ
        return cls(
            email=resolve_secret(source.get("SKYLIGHT_EMAIL")),
            password=resolve_secret(source.get("SKYLIGHT_PASSWORD")),
            base_url=(source.get("SKYLIGHT_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
            frame_id=source.get("SKYLIGHT_FRAME_ID"),
            timezone=source.get("SKYLIGHT_TIMEZONE"),
        )


def _cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(base) / "pyskylight" / "token.json"


class TokenCache:
    """A tiny on-disk cache of the session token (mode 0600)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or _cache_path()

    def load(self, base_url: str) -> Optional[Credentials]:
        """Return cached credentials for ``base_url``, or ``None`` if absent/mismatched."""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        if data.get("base_url") != base_url.rstrip("/"):
            return None
        user_id = data.get("user_id")
        token = data.get("token")
        if not user_id or not token:
            return None
        return Credentials(
            user_id=str(user_id),
            token=str(token),
            subscription_status=data.get("subscription_status"),
        )

    def save(self, credentials: Credentials, base_url: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "base_url": base_url.rstrip("/"),
            "user_id": credentials.user_id,
            "token": credentials.token,
            "subscription_status": credentials.subscription_status,
        }
        # Write then tighten perms to owner-only.
        self.path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            self.path.chmod(0o600)
        except OSError:  # pragma: no cover - platform dependent
            pass

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
