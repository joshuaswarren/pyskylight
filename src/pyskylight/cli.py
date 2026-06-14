"""The ``skylight`` command-line interface.

Thin, JSON-first wrapper over :class:`~pyskylight.client.SkylightClient`, designed to
be driven by humans or by an agent (e.g. the OpenClaw skill). Reads credentials from
the environment (see :mod:`pyskylight.config`), caches the session token, and
re-authenticates automatically if the token has expired.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, List, Optional

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


def _json_arg(raw: Optional[str]) -> Any:
    """Parse a ``--json`` option string into a Python object."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise typer.BadParameter(f"--json must be valid JSON: {exc}")


def _fields(**kw: Any) -> dict:
    """Drop ``None`` values so only explicitly-set options are sent."""
    return {k: v for k, v in kw.items() if v is not None}


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


@app.command("event-add")
def event_add(
    summary: str = typer.Option(..., "--summary"),
    starts_at: Optional[str] = typer.Option(None, "--starts-at", help="ISO datetime."),
    ends_at: Optional[str] = typer.Option(None, "--ends-at", help="ISO datetime."),
    all_day: Optional[bool] = typer.Option(None, "--all-day/--timed", help="All-day event."),
    timezone: Optional[str] = typer.Option(None, "--tz", help="IANA timezone."),
    category_id: Optional[List[str]] = typer.Option(
        None, "--category-id", help="Profile/category id (repeatable)."
    ),
    rrule: Optional[List[str]] = typer.Option(
        None, "--rrule", help="iCal RRULE string (repeatable)."
    ),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create a calendar event."""
    fid = _frame(frame)
    fields = {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "all_day": all_day,
        "timezone": timezone,
        "category_ids": list(category_id) if category_id else None,
        "rrule": list(rrule) if rrule else None,
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    _emit(_run(lambda c: _resource_dict(c.create_calendar_event(fid, summary, **fields))))


@app.command("event-update")
def event_update(
    event_id: str = typer.Argument(...),
    summary: Optional[str] = typer.Option(None, "--summary"),
    starts_at: Optional[str] = typer.Option(None, "--starts-at"),
    ends_at: Optional[str] = typer.Option(None, "--ends-at"),
    all_day: Optional[bool] = typer.Option(None, "--all-day/--timed"),
    timezone: Optional[str] = typer.Option(None, "--tz"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a calendar event."""
    fid = _frame(frame)
    fields = {
        k: v
        for k, v in {
            "summary": summary,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "all_day": all_day,
            "timezone": timezone,
        }.items()
        if v is not None
    }
    _emit(_run(lambda c: _resource_dict(c.update_calendar_event(fid, event_id, **fields))))


@app.command("event-delete")
def event_delete(
    event_id: str = typer.Argument(...),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Delete a calendar event."""
    fid = _frame(frame)
    _run(lambda c: c.delete_calendar_event(fid, event_id))
    _emit({"ok": True, "deleted": event_id})


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


@app.command("update-recipe")
def update_recipe(
    recipe_id: str = typer.Argument(...),
    summary: Optional[str] = typer.Option(None, "--summary"),
    description: Optional[str] = typer.Option(None, "--description"),
    meal_category_id: Optional[str] = typer.Option(None, "--meal-category-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a recipe (PATCH)."""
    fid = _frame(frame)
    fields = {
        k: v
        for k, v in {
            "summary": summary,
            "description": description,
            "meal_category_id": meal_category_id,
        }.items()
        if v is not None
    }
    _emit(_run(lambda c: _resource_dict(c.update_recipe(fid, recipe_id, **fields))))


@app.command("grocery-add")
def grocery_add(
    recipe_id: str = typer.Argument(...),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Add a recipe's ingredients to the (default) grocery list."""
    fid = _frame(frame)
    _emit(_run(lambda c: {"ok": True, "result": c.add_recipe_to_grocery_list(fid, recipe_id)}))


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


@app.command("plan-update")
def plan_update(
    sitting_id: str = typer.Argument(...),
    date: Optional[str] = typer.Option(None, "--date"),
    meal_category_id: Optional[str] = typer.Option(None, "--meal-category-id"),
    recipe_id: Optional[str] = typer.Option(None, "--recipe-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a planned meal (sitting)."""
    fid = _frame(frame)
    fields = {
        k: v
        for k, v in {
            "date": date,
            "meal_category_id": meal_category_id,
            "meal_recipe_id": recipe_id,
        }.items()
        if v is not None
    }
    _emit(_run(lambda c: _resource_dict(c.update_sitting(fid, sitting_id, **fields))))


@app.command("plan-remove")
def plan_remove(
    sitting_id: str = typer.Argument(...),
    date: str = typer.Option(..., "--date", help="Instance date (YYYY-MM-DD) to remove."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Remove a planned meal instance on a specific date."""
    fid = _frame(frame)
    _run(lambda c: c.delete_sitting(fid, sitting_id, date))
    _emit({"ok": True, "removed": sitting_id, "date": date})


# --------------------------------------------------------------------------- #
# Lists / chores
# --------------------------------------------------------------------------- #
@app.command()
def lists(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List shopping / to-do lists."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_lists(fid)))


@app.command("list-add")
def list_add(
    list_id: str = typer.Argument(...),
    label: str = typer.Option(..., "--label"),
    section: Optional[str] = typer.Option(None, "--section"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Add an item to a shopping / to-do list."""
    fid = _frame(frame)
    _emit(_run(lambda c: {"ok": True, "result": c.add_list_item(fid, list_id, label, section)}))


@app.command()
def chores(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List chores."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_chores(fid)))


# --------------------------------------------------------------------------- #
# Single-resource reads (Tier 0)
# --------------------------------------------------------------------------- #
@app.command("plan-show")
def plan_show(
    sitting_id: str = typer.Argument(...),
    include: Optional[str] = typer.Option(None, "--include"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Show one planned meal (sitting)."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_sitting(fid, sitting_id, include=include)))


@app.command("list-show")
def list_show(
    list_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Show one list (with items + sections)."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_list(fid, list_id)))


@app.command("list-items")
def list_items(
    list_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """List the items of a list."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_list_items(fid, list_id)))


@app.command()
def category(
    category_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Show one profile / category."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_category(fid, category_id)))


@app.command("update-meal-category")
def update_meal_category(
    category_id: str = typer.Argument(...),
    json_body: Optional[str] = typer.Option(None, "--json", help="JSON body of fields to update."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a meal category (body verified live; pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_meal_category(fid, category_id, **body)))


# --------------------------------------------------------------------------- #
# Chores (Tier 1)
# --------------------------------------------------------------------------- #
@app.command("chore-add")
def chore_add(
    summary: str = typer.Option(..., "--summary"),
    start: Optional[str] = typer.Option(None, "--start"),
    start_time: Optional[str] = typer.Option(None, "--start-time"),
    reward_points: Optional[int] = typer.Option(None, "--reward-points"),
    category_id: Optional[str] = typer.Option(None, "--category-id"),
    recurring: Optional[bool] = typer.Option(None, "--recurring/--once"),
    rrule: Optional[List[str]] = typer.Option(None, "--rrule", help="RRULE (repeatable)."),
    up_for_grabs: Optional[bool] = typer.Option(None, "--up-for-grabs/--assigned"),
    emoji: Optional[str] = typer.Option(None, "--emoji"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create a chore."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.create_chore(
                fid,
                summary,
                start=start,
                start_time=start_time,
                reward_points=reward_points,
                category_id=category_id,
                recurring=recurring,
                recurrence_set=list(rrule) if rrule else None,
                up_for_grabs=up_for_grabs,
                emoji_icon=emoji,
            )
        )
    )


@app.command("chore-add-multiple")
def chore_add_multiple(
    json_body: str = typer.Option(..., "--json", help="JSON array/object of chores."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Bulk-create chores from a JSON body."""
    fid = _frame(frame)
    body = _json_arg(json_body)
    _emit(_run(lambda c: c.create_chores(fid, body)))


@app.command("chore-update")
def chore_update(
    chore_id: str = typer.Argument(...),
    summary: Optional[str] = typer.Option(None, "--summary"),
    start: Optional[str] = typer.Option(None, "--start"),
    start_time: Optional[str] = typer.Option(None, "--start-time"),
    reward_points: Optional[int] = typer.Option(None, "--reward-points"),
    status: Optional[str] = typer.Option(None, "--status"),
    category_id: Optional[str] = typer.Option(None, "--category-id"),
    emoji: Optional[str] = typer.Option(None, "--emoji"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a chore."""
    fid = _frame(frame)
    fields = _fields(
        summary=summary,
        start=start,
        start_time=start_time,
        reward_points=reward_points,
        status=status,
        category_id=category_id,
        emoji_icon=emoji,
    )
    _emit(_run(lambda c: c.update_chore(fid, chore_id, **fields)))


@app.command("chore-complete")
def chore_complete(
    chore_id: str = typer.Argument(...),
    instance_date: Optional[str] = typer.Option(None, "--instance-date"),
    status: str = typer.Option("complete", "--status"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Mark a chore (or recurring instance) complete/incomplete."""
    fid = _frame(frame)
    _emit(
        _run(lambda c: c.complete_chore(fid, chore_id, instance_date=instance_date, status=status))
    )


@app.command("chore-delete")
def chore_delete(
    chore_id: str = typer.Argument(...),
    apply_to: Optional[str] = typer.Option(None, "--apply-to", help="one|all|future"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Delete a chore."""
    fid = _frame(frame)
    _run(lambda c: c.delete_chore(fid, chore_id, apply_to=apply_to))
    _emit({"ok": True, "deleted": chore_id})


# --------------------------------------------------------------------------- #
# Lists & list items (Tier 1)
# --------------------------------------------------------------------------- #
@app.command("list-create")
def list_create(
    label: str = typer.Option(..., "--label"),
    color: Optional[str] = typer.Option(None, "--color"),
    kind: Optional[str] = typer.Option(None, "--kind", help="shopping|to_do"),
    hide_from_frame: Optional[bool] = typer.Option(None, "--hide-from-frame/--show-on-frame"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create a list."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.create_list(
                fid, label, color=color, kind=kind, hide_from_frame=hide_from_frame
            )
        )
    )


@app.command("list-update")
def list_update(
    list_id: str = typer.Argument(...),
    label: Optional[str] = typer.Option(None, "--label"),
    color: Optional[str] = typer.Option(None, "--color"),
    kind: Optional[str] = typer.Option(None, "--kind"),
    hide_from_frame: Optional[bool] = typer.Option(None, "--hide-from-frame/--show-on-frame"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a list."""
    fid = _frame(frame)
    fields = _fields(label=label, color=color, kind=kind, hide_from_frame=hide_from_frame)
    _emit(_run(lambda c: c.update_list(fid, list_id, **fields)))


@app.command("list-delete")
def list_delete(
    list_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Delete a list."""
    fid = _frame(frame)
    _run(lambda c: c.delete_list(fid, list_id))
    _emit({"ok": True, "deleted": list_id})


@app.command("list-item-update")
def list_item_update(
    list_id: str = typer.Argument(...),
    item_id: str = typer.Argument(...),
    label: Optional[str] = typer.Option(None, "--label"),
    status: Optional[str] = typer.Option(None, "--status", help="pending|completed"),
    position: Optional[int] = typer.Option(None, "--position"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a list item."""
    fid = _frame(frame)
    fields = _fields(label=label, status=status, position=position)
    _emit(_run(lambda c: c.update_list_item(fid, list_id, item_id, **fields)))


@app.command("list-item-complete")
def list_item_complete(
    list_id: str = typer.Argument(...),
    item_id: str = typer.Argument(...),
    completed: bool = typer.Option(True, "--completed/--uncompleted"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Mark a list item completed / pending."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.complete_list_item(fid, list_id, item_id, completed=completed)))


@app.command("list-item-delete")
def list_item_delete(
    list_id: str = typer.Argument(...),
    item_id: str = typer.Argument(...),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Delete a single list item."""
    fid = _frame(frame)
    _run(lambda c: c.delete_list_item(fid, list_id, item_id))
    _emit({"ok": True, "deleted": item_id})


@app.command("list-items-delete")
def list_items_delete(
    list_id: str = typer.Argument(...),
    item_id: List[str] = typer.Option(..., "--id", help="Item id (repeatable)."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Bulk-delete list items."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.delete_list_items(fid, list_id, list(item_id))))


@app.command("list-item-move")
def list_item_move(
    list_id: str = typer.Argument(...),
    item_id: str = typer.Argument(...),
    after_item_id: Optional[str] = typer.Option(None, "--after-item-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Reorder a list item (place it after another, or first if omitted)."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.move_list_item(fid, list_id, item_id, after_item_id=after_item_id)))


@app.command("list-items-section")
def list_items_section(
    list_id: str = typer.Argument(...),
    section: str = typer.Option(..., "--section"),
    item_id: List[str] = typer.Option(..., "--id", help="Item id (repeatable)."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Set the section of several list items at once."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.set_list_items_section(fid, list_id, list(item_id), section)))


# --------------------------------------------------------------------------- #
# Categories / profiles (Tier 1)
# --------------------------------------------------------------------------- #
@app.command("category-add")
def category_add(
    label: str = typer.Option(..., "--label"),
    color: str = typer.Option(..., "--color"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create a profile / category."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.create_category(fid, label, color)))


@app.command("category-find-or-create")
def category_find_or_create(
    label: str = typer.Option(..., "--label"),
    color: str = typer.Option(..., "--color"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Find or create a category by label/color (idempotent)."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.find_or_create_category(fid, label, color)))


@app.command("category-update")
def category_update(
    category_id: str = typer.Argument(...),
    label: Optional[str] = typer.Option(None, "--label"),
    color: Optional[str] = typer.Option(None, "--color"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a category."""
    fid = _frame(frame)
    fields = _fields(label=label, color=color)
    _emit(_run(lambda c: c.update_category(fid, category_id, **fields)))


@app.command("category-delete")
def category_delete(
    category_id: str = typer.Argument(...),
    reassign_to_id: Optional[str] = typer.Option(None, "--reassign-to-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Delete a category (optionally reassign its items)."""
    fid = _frame(frame)
    _run(lambda c: c.delete_category(fid, category_id, reassign_to_id=reassign_to_id))
    _emit({"ok": True, "deleted": category_id})


# --------------------------------------------------------------------------- #
# Sitting instances (Tier 1)
# --------------------------------------------------------------------------- #
@app.command("plan-instances")
def plan_instances(
    sitting_id: str = typer.Argument(...),
    date_min: Optional[str] = typer.Option(None, "--from"),
    date_max: Optional[str] = typer.Option(None, "--to"),
    include: Optional[str] = typer.Option(None, "--include"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """List dated instances of a (recurring) planned meal."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.list_sitting_instances(
                fid, sitting_id, date_min=date_min, date_max=date_max, include=include
            )
        )
    )


@app.command("plan-instance-update")
def plan_instance_update(
    sitting_id: str = typer.Argument(...),
    date: str = typer.Option(..., "--date", help="Instance date (YYYY-MM-DD)."),
    recipe_id: Optional[str] = typer.Option(None, "--recipe-id"),
    meal_category_id: Optional[str] = typer.Option(None, "--meal-category-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a single dated instance of a planned meal."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.update_sitting_instance(
                fid, sitting_id, date, meal_recipe_id=recipe_id, meal_category_id=meal_category_id
            )
        )
    )


# --------------------------------------------------------------------------- #
# Calendar integration (Tier 2)
# --------------------------------------------------------------------------- #
@app.command()
def calendars(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List connected calendar accounts."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_calendars(fid)))


@app.command("calendar-account")
def calendar_account(
    account_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Show one connected calendar account."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_calendar_account(fid, account_id)))


@app.command("calendar-account-update")
def calendar_account_update(
    account_id: str = typer.Argument(...),
    active_calendar: List[str] = typer.Option(..., "--active-calendar", help="Repeatable."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Set which sub-calendars of a connected account are active."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.update_calendar_account(fid, account_id, list(active_calendar))))


@app.command("calendar-link")
def calendar_link(
    redirect_url: str = typer.Option(..., "--redirect-url"),
    failure_redirect_url: str = typer.Option(..., "--failure-redirect-url"),
    two_way_sync: Optional[bool] = typer.Option(None, "--two-way-sync/--one-way-sync"),
    provider: Optional[str] = typer.Option(None, "--provider"),
    login_hint: Optional[str] = typer.Option(None, "--login-hint"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Get the OAuth URL to connect Google/etc. to this frame."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.calendar_authorization_url(
                fid,
                redirect_url=redirect_url,
                failure_redirect_url=failure_redirect_url,
                two_way_sync=two_way_sync,
                provider=provider,
                login_hint=login_hint,
            )
        )
    )


@app.command()
def webcals(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List ICS/webcal subscriptions."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_webcal_accounts(fid)))


@app.command("webcal-add")
def webcal_add(
    sync_url: str = typer.Option(..., "--sync-url"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Subscribe the frame to an .ics / webcal URL."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.subscribe_webcal(fid, sync_url)))


@app.command("source-calendars")
def source_calendars(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List source calendars."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_source_calendars(fid)))


@app.command("source-calendar")
def source_calendar(
    calendar_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Show one source calendar."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_source_calendar(fid, calendar_id)))


@app.command("source-calendar-add")
def source_calendar_add(
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create a source calendar (body verified live; pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.create_source_calendar(fid, **body)))


@app.command("source-calendar-update")
def source_calendar_update(
    calendar_id: str = typer.Argument(...),
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a source calendar (pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_source_calendar(fid, calendar_id, **body)))


@app.command("source-calendar-delete")
def source_calendar_delete(
    calendar_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Delete a source calendar."""
    fid = _frame(frame)
    _run(lambda c: c.delete_source_calendar(fid, calendar_id))
    _emit({"ok": True, "deleted": calendar_id})


@app.command("source-calendar-default")
def source_calendar_default(
    calendar_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Set the default source calendar for new events."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.set_default_source_calendar(fid, calendar_id)))


@app.command("events-search")
def events_search(
    query: str = typer.Option(..., "--query"),
    timezone: Optional[str] = typer.Option(None, "--tz"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Search calendar events."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.search_calendar_events(fid, query, timezone=timezone)))


@app.command()
def countdowns(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List countdown events."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_countdowns(fid)))


@app.command("event-invitees")
def event_invitees(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List recently-invited email suggestions."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.recent_invited_emails(fid)))


@app.command("event-notifications")
def event_notifications(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """Show event-notification settings."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_event_notification_settings(fid)))


@app.command("event-notifications-update")
def event_notifications_update(
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update event-notification settings (pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_event_notification_settings(fid, **body)))


@app.command("reminder-notification")
def reminder_notification(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """Show reminder-notification config."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_reminder_notification(fid)))


@app.command("reminder-notification-update")
def reminder_notification_update(
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update reminder-notification config (pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_reminder_notification(fid, **body)))


@app.command("source-calendar-categorize")
def source_calendar_categorize(
    calendar_id: str = typer.Argument(...),
    json_body: str = typer.Option(..., "--json", help="categorizations array/object."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Map a source calendar's events to categories (pass --json)."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.set_source_calendar_categorizations(fid, calendar_id, _json_arg(json_body))
        )
    )


@app.command("category-categorize")
def category_categorize(
    category_id: str = typer.Argument(...),
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Set category-side source-calendar categorizations (pass --json)."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.set_category_source_calendar_categorizations(
                fid, category_id, _json_arg(json_body)
            )
        )
    )


@app.command("task-box")
def task_box(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List task-box (quick task) items."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_task_box_items(fid)))


@app.command("task-box-add")
def task_box_add(
    title: str = typer.Option(..., "--title"), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Add a task-box item."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.create_task_box_item(fid, title)))


@app.command("task-box-update")
def task_box_update(
    item_id: str = typer.Argument(...),
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a task-box item (pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_task_box_item(fid, item_id, **body)))


@app.command("task-box-delete")
def task_box_delete(
    item_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Delete a task-box item."""
    fid = _frame(frame)
    _run(lambda c: c.delete_task_box_item(fid, item_id))
    _emit({"ok": True, "deleted": item_id})


@app.command()
def routines(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List routines."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_routines(fid)))


@app.command("routine-add")
def routine_add(
    title: str = typer.Option(..., "--title"),
    assignee_id: str = typer.Option(..., "--assignee-id"),
    steps_json: str = typer.Option(..., "--json", help="JSON array of steps."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create a routine."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.create_routine(fid, title, assignee_id, _json_arg(steps_json))))


@app.command("routine-update")
def routine_update(
    routine_id: str = typer.Argument(...),
    title: Optional[str] = typer.Option(None, "--title"),
    assignee_id: Optional[str] = typer.Option(None, "--assignee-id"),
    steps_json: Optional[str] = typer.Option(None, "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a routine."""
    fid = _frame(frame)
    fields = _fields(title=title, assignee_id=assignee_id, steps=_json_arg(steps_json))
    _emit(_run(lambda c: c.update_routine(fid, routine_id, **fields)))


@app.command("routine-delete")
def routine_delete(
    routine_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Delete a routine."""
    fid = _frame(frame)
    _run(lambda c: c.delete_routine(fid, routine_id))
    _emit({"ok": True, "deleted": routine_id})


@app.command("routines-reorder")
def routines_reorder(
    routine_id: List[str] = typer.Option(..., "--id", help="Routine id in order (repeatable)."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Reorder routines."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.reorder_routines(fid, list(routine_id))))


# --------------------------------------------------------------------------- #
# Rewards (Tier 3)
# --------------------------------------------------------------------------- #
@app.command()
def rewards(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List rewards."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_rewards(fid)))


@app.command()
def reward(
    reward_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Show one reward."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_reward(fid, reward_id)))


@app.command("reward-add")
def reward_add(
    name: str = typer.Option(..., "--name"),
    point_value: int = typer.Option(..., "--point-value"),
    category_id: Optional[List[str]] = typer.Option(None, "--category-id", help="Repeatable."),
    emoji: Optional[str] = typer.Option(None, "--emoji"),
    description: Optional[str] = typer.Option(None, "--description"),
    respawn: Optional[bool] = typer.Option(None, "--respawn/--no-respawn"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create a reward."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.create_reward(
                fid,
                name,
                point_value,
                category_ids=list(category_id) if category_id else None,
                emoji_icon=emoji,
                description=description,
                respawn_on_redemption=respawn,
            )
        )
    )


@app.command("reward-update")
def reward_update(
    reward_id: str = typer.Argument(...),
    name: Optional[str] = typer.Option(None, "--name"),
    point_value: Optional[int] = typer.Option(None, "--point-value"),
    emoji: Optional[str] = typer.Option(None, "--emoji"),
    description: Optional[str] = typer.Option(None, "--description"),
    respawn: Optional[bool] = typer.Option(None, "--respawn/--no-respawn"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a reward."""
    fid = _frame(frame)
    fields = _fields(
        name=name,
        point_value=point_value,
        emoji_icon=emoji,
        description=description,
        respawn_on_redemption=respawn,
    )
    _emit(_run(lambda c: c.update_reward(fid, reward_id, **fields)))


@app.command("reward-delete")
def reward_delete(
    reward_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Delete a reward."""
    fid = _frame(frame)
    _run(lambda c: c.delete_reward(fid, reward_id))
    _emit({"ok": True, "deleted": reward_id})


@app.command("reward-redeem")
def reward_redeem(
    reward_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Redeem a reward (spend points)."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.redeem_reward(fid, reward_id)))


@app.command("reward-unredeem")
def reward_unredeem(
    reward_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Un-redeem a reward."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.unredeem_reward(fid, reward_id)))


@app.command("reward-points")
def reward_points(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """Show reward-point balances."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_reward_points(fid)))


@app.command("reward-points-set")
def reward_points_set(
    points: int = typer.Option(..., "--points"),
    category_id: List[str] = typer.Option(..., "--category-id", help="Repeatable."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Set reward points for one or more categories."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.set_reward_points(fid, list(category_id), points)))


# --------------------------------------------------------------------------- #
# Messages / photos (Tier 3)
# --------------------------------------------------------------------------- #
@app.command()
def messages(
    page: Optional[str] = typer.Option(None, "--page"),
    page_token: Optional[str] = typer.Option(None, "--page-token"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """List photos / messages."""
    fid = _frame(frame)
    params = _fields(page=page, page_token=page_token)
    _emit(_run(lambda c: c.list_messages(fid, **params)))


@app.command()
def message(
    message_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Show one message / photo."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_message(fid, message_id)))


@app.command("message-delete")
def message_delete(
    message_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Delete a message / photo."""
    fid = _frame(frame)
    _run(lambda c: c.delete_message(fid, message_id))
    _emit({"ok": True, "deleted": message_id})


@app.command("messages-delete")
def messages_delete(
    message_id: List[str] = typer.Option(..., "--id", help="Message id (repeatable)."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Bulk-delete messages / photos."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.delete_messages(fid, list(message_id))))


@app.command("messages-copy")
def messages_copy(
    message_id: List[str] = typer.Option(..., "--id", help="Message id (repeatable)."),
    to_frame: List[str] = typer.Option(..., "--to-frame", help="Destination frame (repeatable)."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Copy photos to other frames."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.copy_messages_to_frames(fid, list(message_id), list(to_frame))))


@app.command("message-caption")
def message_caption(
    message_id: str = typer.Argument(...),
    caption: str = typer.Option(..., "--caption"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Set a message's caption."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.set_message_caption(fid, message_id, caption)))


@app.command("message-likes")
def message_likes(
    message_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """List likes on a message."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_message_likes(fid, message_id)))


@app.command("message-like")
def message_like(
    message_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Like a message."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.like_message(fid, message_id)))


@app.command("message-unlike")
def message_unlike(
    message_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Remove a like from a message."""
    fid = _frame(frame)
    _run(lambda c: c.unlike_message(fid, message_id))
    _emit({"ok": True, "unliked": message_id})


@app.command("message-comments")
def message_comments(
    message_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """List comments on a message."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_message_comments(fid, message_id)))


@app.command("message-comment-add")
def message_comment_add(
    message_id: str = typer.Argument(...),
    body: str = typer.Option(..., "--body"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Comment on a message."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.comment_message(fid, message_id, body)))


@app.command("message-comment-delete")
def message_comment_delete(
    message_id: str = typer.Argument(...),
    comment_id: str = typer.Argument(...),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Delete a comment."""
    fid = _frame(frame)
    _run(lambda c: c.delete_message_comment(fid, message_id, comment_id))
    _emit({"ok": True, "deleted": comment_id})


@app.command("photo-upload")
def photo_upload(
    file: str = typer.Option(..., "--file", help="Path to the image/video to upload."),
    caption: Optional[str] = typer.Option(None, "--caption"),
    trim_start: Optional[float] = typer.Option(None, "--trim-start"),
    trim_end: Optional[float] = typer.Option(None, "--trim-end"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Upload a photo/video to the frame (two-step; shape verified live)."""
    fid = _frame(frame)
    _emit(
        _run(
            lambda c: c.upload_photo(
                fid, file, caption=caption, trim_start=trim_start, trim_end=trim_end
            )
        )
    )


@app.command("upload-credentials")
def upload_credentials() -> None:
    """Fetch cloud upload credentials."""
    _emit(_run(lambda c: c.cloud_upload_credentials()))


# --------------------------------------------------------------------------- #
# Albums (Tier 3)
# --------------------------------------------------------------------------- #
@app.command()
def albums(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List albums."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_albums(fid)))


@app.command("album-add")
def album_add(
    title: str = typer.Option(..., "--title"), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Create an album."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.create_album(fid, title)))


@app.command("album-update")
def album_update(
    album_id: str = typer.Argument(...),
    title: str = typer.Option(..., "--title"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Rename an album."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.update_album(fid, album_id, title)))


@app.command("album-delete")
def album_delete(
    album_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Delete an album."""
    fid = _frame(frame)
    _run(lambda c: c.delete_album(fid, album_id))
    _emit({"ok": True, "deleted": album_id})


@app.command("album-messages")
def album_messages(
    album_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """List photos in an album."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_album_messages(fid, album_id)))


@app.command("album-message-ids")
def album_message_ids(
    album_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """List all message ids in an album."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_album_message_ids(fid, album_id)))


@app.command("album-add-photos")
def album_add_photos(
    album_id: List[str] = typer.Option(..., "--album-id", help="Repeatable."),
    message_id: List[str] = typer.Option(..., "--message-id", help="Repeatable."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Add photos to albums."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.add_to_albums(fid, list(album_id), list(message_id))))


@app.command("album-remove-photos")
def album_remove_photos(
    album_id: List[str] = typer.Option(..., "--album-id", help="Repeatable."),
    message_id: List[str] = typer.Option(..., "--message-id", help="Repeatable."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Remove photos from albums."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.remove_from_albums(fid, list(album_id), list(message_id))))


# --------------------------------------------------------------------------- #
# Month-in-review & global reference reads (Tier 3)
# --------------------------------------------------------------------------- #
@app.command("month-in-review")
def month_in_review(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """Show the latest month-in-review."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.month_in_review(fid)))


@app.command("month-in-reviews")
def month_in_reviews(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List all month-in-review entries."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_month_in_reviews(fid)))


@app.command()
def avatars() -> None:
    """List the global avatar catalog."""
    _emit(_run(lambda c: c.list_avatars()))


@app.command()
def colors() -> None:
    """List the global color palette."""
    _emit(_run(lambda c: c.list_colors()))


@app.command()
def activities() -> None:
    """List the account activity feed."""
    _emit(_run(lambda c: c.list_activities()))


# --------------------------------------------------------------------------- #
# Devices & alarms (Tier 4)
# --------------------------------------------------------------------------- #
@app.command()
def devices(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List devices on the frame."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_devices(fid)))


@app.command()
def device(
    device_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Show one device."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_device(fid, device_id)))


@app.command("device-update")
def device_update(
    device_id: str = typer.Argument(...),
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a device (body verified live; pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_device(fid, device_id, **body)))


@app.command("device-delete")
def device_delete(
    device_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Remove a device from the frame."""
    fid = _frame(frame)
    _run(lambda c: c.delete_device(fid, device_id))
    _emit({"ok": True, "deleted": device_id})


@app.command("device-activation-code")
def device_activation_code(
    device_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Generate an activation code for a device."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.device_activation_code(fid, device_id)))


@app.command("device-reset")
def device_reset(
    device_id: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", help="Confirm this destructive factory reset."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Factory-reset a device (destructive; requires --yes)."""
    if not yes:
        raise typer.BadParameter("Refusing to reset a device without --yes.")
    fid = _frame(frame)
    _emit(_run(lambda c: c.reset_device(fid, device_id)))


@app.command()
def alarms(
    device_id: str = typer.Option(..., "--device-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """List a device's alarms (Buddy)."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_alarms(fid, device_id)))


@app.command("alarm-add")
def alarm_add(
    device_id: str = typer.Option(..., "--device-id"),
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create an alarm (body verified live; pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.create_alarm(fid, device_id, **body)))


@app.command("alarm-update")
def alarm_update(
    alarm_id: str = typer.Argument(...),
    device_id: str = typer.Option(..., "--device-id"),
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update an alarm (pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_alarm(fid, device_id, alarm_id, **body)))


@app.command("alarm-delete")
def alarm_delete(
    alarm_id: str = typer.Argument(...),
    device_id: str = typer.Option(..., "--device-id"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Delete an alarm."""
    fid = _frame(frame)
    _run(lambda c: c.delete_alarm(fid, device_id, alarm_id))
    _emit({"ok": True, "deleted": alarm_id})


# --------------------------------------------------------------------------- #
# Household members & config (Tier 4)
# --------------------------------------------------------------------------- #
@app.command()
def members(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List household members."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_frame_users(fid)))


@app.command("member-invite")
def member_invite(
    email: str = typer.Option(..., "--email"), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Invite a household member by email."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.invite_frame_user(fid, email)))


@app.command("member-approve")
def member_approve(
    user_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Approve a pending member."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.approve_frame_user(fid, user_id)))


@app.command("member-remove")
def member_remove(
    user_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Remove a household member."""
    fid = _frame(frame)
    _run(lambda c: c.remove_frame_user(fid, user_id))
    _emit({"ok": True, "removed": user_id})


@app.command("member-update")
def member_update(
    member_id: str = typer.Argument(...),
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update a family member (body verified live; pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_family_member(fid, member_id, **body)))


@app.command("household-config")
def household_config(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """Show household config."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_household_config(fid)))


@app.command("household-config-update")
def household_config_update(
    json_body: str = typer.Option(..., "--json"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update household config (pass --json)."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.update_household_config(fid, **body)))


# --------------------------------------------------------------------------- #
# Environment / misc / frame management (Tier 4)
# --------------------------------------------------------------------------- #
@app.command()
def weather(
    lat: Optional[str] = typer.Option(None, "--lat"),
    lon: Optional[str] = typer.Option(None, "--lon"),
) -> None:
    """Show weather."""
    params = _fields(lat=lat, lon=lon)
    _emit(_run(lambda c: c.get_weather(**params)))


@app.command()
def geolocation() -> None:
    """Show IP-based geolocation."""
    _emit(_run(lambda c: c.get_geolocation()))


@app.command("share-link")
def share_link(
    json_body: Optional[str] = typer.Option(None, "--json"),
) -> None:
    """Generate a OneLink share URL (pass --json for params)."""
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.generate_one_link(**body)))


@app.command("plus-status")
def plus_status(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """Show Skylight Plus subscription status (read)."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_plus_subscriptions(fid)))


@app.command("frame-rename")
def frame_rename(
    name: str = typer.Option(..., "--name"), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Rename a frame."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.frame_rename(fid, name)))


@app.command("frame-settings")
def frame_settings(
    open_to_public: Optional[bool] = typer.Option(None, "--open-to-public/--private"),
    message_viewability: Optional[str] = typer.Option(None, "--message-viewability"),
    timezone: Optional[str] = typer.Option(None, "--timezone"),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Update frame privacy (PUT) and/or timezone (PATCH)."""
    fid = _frame(frame)
    privacy = _fields(open_to_public=open_to_public, message_viewability=message_viewability)
    if not privacy and timezone is None:
        raise typer.BadParameter("Nothing to update (pass privacy flags and/or --timezone).")

    def act(c: SkylightClient) -> Any:
        out: dict = {}
        if privacy:
            out["settings"] = c.update_frame_settings(fid, **privacy)
        if timezone is not None:
            out["timezone"] = c.update_frame_timezone(fid, timezone)
        return out

    _emit(_run(act))


@app.command("frame-hide")
def frame_hide(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """Hide a frame from your list."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.hide_frame(fid)))


@app.command("frame-activation-code")
def frame_activation_code(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """Generate an activation code for the frame."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.frame_activation_code(fid)))


# --------------------------------------------------------------------------- #
# AI Sidekick / auto-creation intents (Tier 5)
# --------------------------------------------------------------------------- #
@app.command("ai-intents")
def ai_intents(frame: Optional[str] = typer.Option(None, "--frame")) -> None:
    """List AI auto-creation intents."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.list_auto_creation_intents(fid)))


@app.command("ai-intent")
def ai_intent(
    intent_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Show one AI intent."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.get_auto_creation_intent(fid, intent_id)))


@app.command("ai-intent-create")
def ai_intent_create(
    intent_type: str = typer.Option(..., "--type", help="list|recipe|event|meal_plan|..."),
    json_body: Optional[str] = typer.Option(None, "--json", help="Prompt payload."),
    frame: Optional[str] = typer.Option(None, "--frame"),
) -> None:
    """Create an AI auto-creation intent."""
    fid = _frame(frame)
    body = _json_arg(json_body) or {}
    _emit(_run(lambda c: c.create_auto_creation_intent(fid, intent_type, **body)))


@app.command("ai-intent-approve")
def ai_intent_approve(
    intent_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Approve an AI intent's draft."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.approve_auto_creation_intent(fid, intent_id)))


@app.command("ai-intent-retry")
def ai_intent_retry(
    intent_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Retry an AI intent's draft."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.retry_auto_creation_intent(fid, intent_id)))


@app.command("ai-intent-undo")
def ai_intent_undo(
    intent_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """Undo an AI intent."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.undo_auto_creation_intent(fid, intent_id)))


@app.command("ai-intent-items")
def ai_intent_items(
    intent_id: str = typer.Argument(...), frame: Optional[str] = typer.Option(None, "--frame")
) -> None:
    """List items an approved AI intent created."""
    fid = _frame(frame)
    _emit(_run(lambda c: c.auto_creation_intent_items(fid, intent_id)))


def main() -> None:  # pragma: no cover - entry point shim
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
