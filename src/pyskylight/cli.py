"""The ``skylight`` command-line interface.

Thin, JSON-first wrapper over :class:`~pyskylight.client.SkylightClient`, designed to
be driven by humans or by an agent (e.g. the OpenClaw skill). Reads credentials from
the environment (see :mod:`pyskylight.config`), caches the session token, and
re-authenticates automatically if the token has expired.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Optional

import typer

from .auth import refresh
from .client import SkylightClient
from .config import Settings, TokenCache
from .errors import SkylightAuthError, SkylightError
from .models import Resource

app = typer.Typer(
    add_completion=False,
    help="Interact with a Skylight Calendar / Buddy household (unofficial API).",
    no_args_is_help=True,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _emit(obj: Any) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def _resource_dict(resource: Resource) -> dict:
    return {
        "id": resource.id,
        "type": resource.type,
        "attributes": resource.attributes,
        "relationships": resource.relationships,
    }


def _build_client(settings: Settings, credentials_required: bool = True) -> SkylightClient:
    """Construct a client from cached token or by logging in.

    This is the single seam tests patch.
    """
    cache = TokenCache()
    creds = cache.load(settings.base_url)
    if creds is not None:
        if not creds.is_expired(time.time()):
            return SkylightClient(creds, base_url=settings.base_url)
        if creds.refresh_token:
            try:
                fresh = refresh(creds.refresh_token, base_url=settings.base_url)
                cache.save(fresh, settings.base_url)
                return SkylightClient(fresh, base_url=settings.base_url)
            except SkylightError:
                pass  # refresh failed; fall through to a full login if we can
    if settings.email and settings.password:
        client = SkylightClient.login(settings.email, settings.password, base_url=settings.base_url)
        cache.save(client.credentials, settings.base_url)
        return client
    raise typer.BadParameter(
        "No cached session and no SKYLIGHT_EMAIL/SKYLIGHT_PASSWORD set. "
        "Run `skylight login` or set the environment variables."
    )


def _run(action: Callable[[SkylightClient], Any]) -> Any:
    """Run ``action`` with a client, re-logging-in once on an auth error."""
    settings = Settings.from_env()
    try:
        client = _build_client(settings)
        try:
            return action(client)
        except SkylightAuthError:
            # Token likely expired: drop cache, re-login if we can, retry once.
            if not (settings.email and settings.password):
                raise
            TokenCache().clear()
            fresh = SkylightClient.login(
                settings.email, settings.password, base_url=settings.base_url
            )
            TokenCache().save(fresh.credentials, settings.base_url)
            return action(fresh)
    except SkylightError as exc:
        typer.echo(json.dumps({"ok": False, "error": str(exc), "type": type(exc).__name__}))
        raise typer.Exit(code=1)


def _frame(frame: Optional[str]) -> str:
    fid = frame or Settings.from_env().frame_id
    if not fid:
        raise typer.BadParameter("No frame id given and SKYLIGHT_FRAME_ID is not set.")
    return fid


# --------------------------------------------------------------------------- #
# Auth / identity
# --------------------------------------------------------------------------- #
@app.command()
def login() -> None:
    """Log in with SKYLIGHT_EMAIL/SKYLIGHT_PASSWORD and cache the session token."""
    settings = Settings.from_env()
    if not (settings.email and settings.password):
        raise typer.BadParameter("Set SKYLIGHT_EMAIL and SKYLIGHT_PASSWORD first.")
    try:
        client = SkylightClient.login(settings.email, settings.password, base_url=settings.base_url)
    except SkylightError as exc:
        typer.echo(json.dumps({"ok": False, "error": str(exc), "type": type(exc).__name__}))
        raise typer.Exit(code=1)
    TokenCache().save(client.credentials, settings.base_url)
    subscription = None
    try:
        attrs = (client.get_user() or {}).get("data", {}).get("attributes", {})
        subscription = attrs.get("subscription_status")
    except SkylightError:
        pass
    _emit(
        {
            "ok": True,
            "subscription_status": subscription,
            "is_plus": bool(subscription)
            and str(subscription).lower() not in ("basic", "free", ""),
            "expires_at": client.credentials.expires_at,
        }
    )


@app.command()
def logout() -> None:
    """Delete the cached session token."""
    TokenCache().clear()
    _emit({"ok": True})


@app.command()
def whoami() -> None:
    """Show the current user profile."""
    _emit(_run(lambda c: c.get_user()))


# --------------------------------------------------------------------------- #
# Frames
# --------------------------------------------------------------------------- #
@app.command()
def frames(include_deleted: bool = typer.Option(False, "--include-deleted")) -> None:
    """List frames (households)."""
    _emit(_run(lambda c: [_resource_dict(f) for f in c.list_frames(include_deleted)]))


@app.command()
def frame(frame_id: str = typer.Argument(...)) -> None:
    """Show one frame's details."""
    _emit(_run(lambda c: _resource_dict(c.get_frame(frame_id))))


# --------------------------------------------------------------------------- #
# Calendar
# --------------------------------------------------------------------------- #
@app.command()
def events(
    date_min: str = typer.Option(..., "--from", help="Start (ISO datetime)."),
    date_max: str = typer.Option(..., "--to", help="End (ISO datetime)."),
    timezone: Optional[str] = typer.Option(None, "--tz", help="IANA timezone."),
    frame: Optional[str] = typer.Option(None, "--frame"),
    include: Optional[str] = typer.Option(None, "--include"),
) -> None:
    """List calendar events in a date window."""
    tz = timezone or Settings.from_env().timezone
    if not tz:
        raise typer.BadParameter("A timezone is required (--tz or SKYLIGHT_TIMEZONE).")
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: [
                _resource_dict(e)
                for e in c.list_calendar_events(fid, date_min, date_max, tz, include)
            ]
        )
    )


# --------------------------------------------------------------------------- #
# Categories / profiles
# --------------------------------------------------------------------------- #
@app.command()
def categories(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List family-member profiles / color categories."""
    fid = _frame(frame)
    _emit(_run(lambda c: [_resource_dict(x) for x in c.list_categories(fid)]))


# --------------------------------------------------------------------------- #
# Meals
# --------------------------------------------------------------------------- #
@app.command("meal-categories")
def meal_categories(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List meal categories (Breakfast/Lunch/Dinner/...)."""
    fid = _frame(frame)
    _emit(_run(lambda c: [_resource_dict(x) for x in c.list_meal_categories(fid)]))


@app.command()
def recipes(
    frame: Optional[str] = typer.Option(None, "--frame"),
    include: str = typer.Option("meal_category", "--include"),
) -> None:
    """List recipes."""
    fid = _frame(frame)
    _emit(_run(lambda c: [_resource_dict(x) for x in c.list_recipes(fid, include)]))


@app.command()
def recipe(
    recipe_id: str = typer.Argument(...),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Show one recipe."""
    fid = _frame(frame)
    _emit(_run(lambda c: _resource_dict(c.get_recipe(fid, recipe_id))))


@app.command("create-recipe")
def create_recipe(
    summary: str = typer.Option(..., "--summary"),
    description: Optional[str] = typer.Option(None, "--description"),
    meal_category_id: Optional[str] = typer.Option(None, "--meal-category-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create a recipe."""
    fid = _frame(frame)
    _emit(
        _run(lambda c: _resource_dict(c.create_recipe(fid, summary, description, meal_category_id)))
    )


@app.command("delete-recipe")
def delete_recipe(
    recipe_id: str = typer.Argument(...),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Delete a recipe."""
    fid = _frame(frame)
    _run(lambda c: c.delete_recipe(fid, recipe_id))
    _emit({"ok": True, "deleted": recipe_id})


@app.command()
def plan(
    frame: Optional[str] = typer.Option(None, "--frame"),
    date_min: Optional[str] = typer.Option(None, "--from"),
    date_max: Optional[str] = typer.Option(None, "--to"),
) -> None:
    """List planned meals (sittings)."""
    fid = _frame(frame)
    _emit(_run(lambda c: [_resource_dict(x) for x in c.list_sittings(fid, date_min, date_max)]))


@app.command("plan-add")
def plan_add(
    date: str = typer.Option(..., "--date"),
    meal_category_id: str = typer.Option(..., "--meal-category-id"),
    recipe_id: Optional[str] = typer.Option(None, "--recipe-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Plan a meal on a date (create a sitting)."""
    fid = _frame(frame)
    _emit(_run(lambda c: _resource_dict(c.create_sitting(fid, date, meal_category_id, recipe_id))))


# --------------------------------------------------------------------------- #
# Lists / chores
# --------------------------------------------------------------------------- #
@app.command()
def lists(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List shopping / to-do lists."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_lists(fid)))


@app.command()
def chores(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List chores."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_chores(fid)))


def main() -> None:  # pragma: no cover - entry point shim
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
