"""The Skylight API client.

``SkylightClient`` wraps the unofficial Skylight private API with typed helpers for
frames, calendar events, categories, lists, chores and — the focus of this project —
Meals (recipes + planned "sittings").

Write-side request bodies (creating recipes / sittings / events) are based on
community reverse-engineering and are marked where they should be confirmed against
live traffic. Each write builds its body in a single small method so it is easy to
adjust once a real request has been captured.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from .auth import Credentials
from .auth import login as _login
from .constants import API_PREFIX, DEFAULT_BASE_URL, DEFAULT_TIMEOUT, USER_AGENT
from .errors import (
    SkylightAPIError,
    SkylightAuthError,
    SkylightNotFoundError,
    SkylightPlusRequiredError,
    SkylightRateLimitError,
)
from .models import (
    CalendarEvent,
    Category,
    Frame,
    MealCategory,
    Recipe,
    Sitting,
    parse_list,
    parse_one,
)


def _compact(body: Dict[str, Any]) -> Dict[str, Any]:
    """Drop ``None`` values so we only send fields the caller actually set."""
    return {k: v for k, v in body.items() if v is not None}


class SkylightClient:
    """A client bound to a single set of Skylight credentials."""

    def __init__(
        self,
        credentials: Credentials,
        *,
        base_url: str = DEFAULT_BASE_URL,
        http: Optional[httpx.Client] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self._owns_client = http is None
        self._http = http or httpx.Client(timeout=timeout)

    # -- lifecycle ---------------------------------------------------------

    @classmethod
    def login(
        cls,
        email: str,
        password: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        http: Optional[httpx.Client] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> "SkylightClient":
        """Log in and return a ready-to-use client."""
        creds = _login(email, password, base_url=base_url, http=http, timeout=timeout)
        return cls(creds, base_url=base_url, http=http, timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> "SkylightClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- low-level request -------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.base_url}{path}"
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Authorization", self.credentials.bearer_header)
        headers.setdefault("Accept", "application/json")
        headers.setdefault("User-Agent", USER_AGENT)
        try:
            resp = self._http.request(method, url, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise SkylightAPIError(f"Network error calling {method} {path}: {exc}") from exc
        self._raise_for_status(resp, method, path)
        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    @staticmethod
    def _raise_for_status(resp: httpx.Response, method: str, path: str) -> None:
        if resp.is_success:
            return
        code = resp.status_code
        if code == 401:
            raise SkylightAuthError("Skylight session is invalid or expired (HTTP 401)")
        if code == 403:
            raise SkylightPlusRequiredError(
                f"{method} {path} was forbidden (HTTP 403) — this often means an "
                "active Skylight Plus subscription is required"
            )
        if code == 404:
            raise SkylightNotFoundError(f"{method} {path} not found (HTTP 404)")
        if code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                retry_seconds = float(retry_after) if retry_after is not None else None
            except ValueError:
                retry_seconds = None
            raise SkylightRateLimitError(
                "Skylight rate limit hit (HTTP 429)", retry_after=retry_seconds
            )
        body = resp.text[:500] if resp.text else None
        raise SkylightAPIError(
            f"{method} {path} failed with HTTP {code}", status_code=code, body=body
        )

    # -- frames / user -----------------------------------------------------

    def list_frames(self, include_deleted: bool = False) -> List[Frame]:
        params = {"show_deleted": "true"} if include_deleted else None
        payload = self._request("GET", f"{API_PREFIX}/frames", params=params)
        return parse_list(payload or {}, Frame)

    def get_frame(self, frame_id: str | int) -> Frame:
        payload = self._request("GET", f"{API_PREFIX}/frames/{frame_id}")
        return parse_one(payload or {}, Frame)

    def get_user(self) -> Dict[str, Any]:
        return self._request("GET", f"{API_PREFIX}/user") or {}

    # -- calendar ----------------------------------------------------------

    def list_calendar_events(
        self,
        frame_id: str | int,
        date_min: str,
        date_max: str,
        timezone: str,
        include: Optional[str] = None,
    ) -> List[CalendarEvent]:
        params = {"date_min": date_min, "date_max": date_max, "timezone": timezone}
        if include:
            params["include"] = include
        payload = self._request(
            "GET", f"{API_PREFIX}/frames/{frame_id}/calendar_events", params=params
        )
        return parse_list(payload or {}, CalendarEvent)

    def create_calendar_event(
        self, frame_id: str | int, summary: str, **fields: Any
    ) -> CalendarEvent:
        body = _compact({"summary": summary, **fields})
        payload = self._request(
            "POST", f"{API_PREFIX}/frames/{frame_id}/calendar_events", json=body
        )
        return parse_one(payload or {}, CalendarEvent)

    def update_calendar_event(
        self, frame_id: str | int, event_id: str | int, **fields: Any
    ) -> CalendarEvent:
        payload = self._request(
            "PUT",
            f"{API_PREFIX}/frames/{frame_id}/calendar_events/{event_id}",
            json=_compact(fields),
        )
        return parse_one(payload or {}, CalendarEvent)

    def delete_calendar_event(self, frame_id: str | int, event_id: str | int) -> None:
        self._request("DELETE", f"{API_PREFIX}/frames/{frame_id}/calendar_events/{event_id}")

    # -- categories / profiles --------------------------------------------

    def list_categories(self, frame_id: str | int) -> List[Category]:
        payload = self._request("GET", f"{API_PREFIX}/frames/{frame_id}/categories")
        return parse_list(payload or {}, Category)

    # -- meals: categories -------------------------------------------------

    def list_meal_categories(self, frame_id: str | int) -> List[MealCategory]:
        payload = self._request("GET", f"{API_PREFIX}/frames/{frame_id}/meals/categories")
        return parse_list(payload or {}, MealCategory)

    # -- meals: recipes ----------------------------------------------------

    def list_recipes(
        self, frame_id: str | int, include: Optional[str] = "meal_category"
    ) -> List[Recipe]:
        params = {"include": include} if include else None
        payload = self._request(
            "GET", f"{API_PREFIX}/frames/{frame_id}/meals/recipes", params=params
        )
        return parse_list(payload or {}, Recipe)

    def get_recipe(self, frame_id: str | int, recipe_id: str | int) -> Recipe:
        payload = self._request("GET", f"{API_PREFIX}/frames/{frame_id}/meals/recipes/{recipe_id}")
        return parse_one(payload or {}, Recipe)

    def create_recipe(
        self,
        frame_id: str | int,
        summary: str,
        description: Optional[str] = None,
        meal_category_id: Optional[str | int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Recipe:
        """Create a recipe.

        Body shape (``{summary, description?, meal_category_id?}``) follows the
        documented MCP client; confirm against live traffic before relying on richer
        fields (structured ingredients/instructions). ``extra`` is merged in to allow
        sending additional fields without a code change.
        """
        body = _compact(
            {
                "summary": summary,
                "description": description,
                "meal_category_id": meal_category_id,
                **(extra or {}),
            }
        )
        payload = self._request("POST", f"{API_PREFIX}/frames/{frame_id}/meals/recipes", json=body)
        return parse_one(payload or {}, Recipe)

    def update_recipe(self, frame_id: str | int, recipe_id: str | int, **fields: Any) -> Recipe:
        # Recipes use PATCH (not PUT) per the reverse-engineered spec.
        payload = self._request(
            "PATCH",
            f"{API_PREFIX}/frames/{frame_id}/meals/recipes/{recipe_id}",
            json=_compact(fields),
        )
        return parse_one(payload or {}, Recipe)

    def delete_recipe(self, frame_id: str | int, recipe_id: str | int) -> None:
        self._request("DELETE", f"{API_PREFIX}/frames/{frame_id}/meals/recipes/{recipe_id}")

    def add_recipe_to_grocery_list(self, frame_id: str | int, recipe_id: str | int) -> Any:
        return self._request(
            "POST",
            f"{API_PREFIX}/frames/{frame_id}/meals/recipes/{recipe_id}/add_to_grocery_list",
        )

    # -- meals: sittings (planned meals) -----------------------------------

    def list_sittings(
        self,
        frame_id: str | int,
        date_min: Optional[str] = None,
        date_max: Optional[str] = None,
    ) -> List[Sitting]:
        params = _compact({"date_min": date_min, "date_max": date_max}) or None
        payload = self._request(
            "GET", f"{API_PREFIX}/frames/{frame_id}/meals/sittings", params=params
        )
        return parse_list(payload or {}, Sitting)

    def create_sitting(
        self,
        frame_id: str | int,
        date: str,
        meal_category_id: str | int,
        meal_recipe_id: Optional[str | int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Sitting:
        """Plan a meal on a date.

        Body ``{date, meal_category_id, meal_recipe_id?}`` follows the documented MCP
        client; ``date`` format (``YYYY-MM-DD`` vs ISO datetime) should be confirmed
        against live traffic.
        """
        body = _compact(
            {
                "date": date,
                "meal_category_id": meal_category_id,
                "meal_recipe_id": meal_recipe_id,
                **(extra or {}),
            }
        )
        payload = self._request("POST", f"{API_PREFIX}/frames/{frame_id}/meals/sittings", json=body)
        # Planning a meal returns ``{"data": [<sitting>]}`` (a list), not a single object.
        data = (payload or {}).get("data")
        if isinstance(data, list):
            data = data[0] if data else {}
        return Sitting.from_jsonapi(data or {})

    def update_sitting(self, frame_id: str | int, sitting_id: str | int, **fields: Any) -> Sitting:
        """Update a planned meal (PATCH). Verb/shape inferred; confirm against live traffic."""
        payload = self._request(
            "PATCH",
            f"{API_PREFIX}/frames/{frame_id}/meals/sittings/{sitting_id}",
            json=_compact(fields),
        )
        return parse_one(payload or {}, Sitting)

    def delete_sitting(self, frame_id: str | int, sitting_id: str | int, date: str) -> None:
        """Remove a planned meal on a specific date.

        Deletes the instance (``.../meals/sittings/{id}/instances/{date}``) — this is
        how the app removes a planned meal. Deleting the sitting resource directly
        (``.../meals/sittings/{id}``) leaves a dangling entry in the plan view.
        """
        self._request(
            "DELETE",
            f"{API_PREFIX}/frames/{frame_id}/meals/sittings/{sitting_id}/instances/{date}",
        )

    # -- lists / chores (read + simple writes) -----------------------------

    def list_lists(self, frame_id: str | int) -> List[Any]:
        payload = self._request("GET", f"{API_PREFIX}/frames/{frame_id}/lists")
        return (payload or {}).get("data") or []

    def add_list_item(
        self,
        frame_id: str | int,
        list_id: str | int,
        label: str,
        section: Optional[str] = None,
    ) -> Any:
        body = _compact({"label": label, "section": section})
        return self._request(
            "POST",
            f"{API_PREFIX}/frames/{frame_id}/lists/{list_id}/list_items",
            json=body,
        )

    def list_chores(self, frame_id: str | int, **params: Any) -> List[Any]:
        payload = self._request(
            "GET",
            f"{API_PREFIX}/frames/{frame_id}/chores",
            params=_compact(params) or None,
        )
        return (payload or {}).get("data") or []

    # ===================================================================== #
    # Full feature coverage (generated from the reverse-engineered surface;
    # write bodies follow the real-code clients, low-confidence shapes accept
    # an ``extra`` / opaque ``body`` escape hatch and are noted for live
    # verification). Reads return the raw decoded JSON payload.
    # ===================================================================== #

    def _frame_path(self, frame_id: str | int, suffix: str) -> str:
        return f"{API_PREFIX}/frames/{frame_id}{suffix}"

    @staticmethod
    def _data(payload: Any) -> Any:
        return (payload or {}).get("data") if isinstance(payload, dict) else payload

    # -- single-resource reads (Tier 0) -----------------------------------

    def get_sitting(
        self, frame_id: str | int, sitting_id: str | int, *, include: Optional[str] = None
    ) -> Any:
        params = {"include": include} if include else None
        return self._request(
            "GET", self._frame_path(frame_id, f"/meals/sittings/{sitting_id}"), params=params
        )

    def get_list(self, frame_id: str | int, list_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/lists/{list_id}"))

    def list_list_items(self, frame_id: str | int, list_id: str | int) -> Any:
        return self._data(
            self._request("GET", self._frame_path(frame_id, f"/lists/{list_id}/list_items"))
        )

    def get_category(self, frame_id: str | int, category_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/categories/{category_id}"))

    def update_meal_category(
        self, frame_id: str | int, category_id: str | int, **fields: Any
    ) -> Any:
        return self._request(
            "PATCH",
            self._frame_path(frame_id, f"/meals/categories/{category_id}"),
            json=_compact(fields),
        )

    # -- chores (Tier 1) --------------------------------------------------

    def create_chore(
        self,
        frame_id: str | int,
        summary: str,
        *,
        start: Optional[str] = None,
        start_time: Optional[str] = None,
        reward_points: Optional[int] = None,
        category_id: Optional[str | int] = None,
        recurring: Optional[bool] = None,
        recurrence_set: Optional[List[str]] = None,
        recurring_until: Optional[str] = None,
        up_for_grabs: Optional[bool] = None,
        emoji_icon: Optional[str] = None,
        status: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = _compact(
            {
                "summary": summary,
                "start": start,
                "start_time": start_time,
                "reward_points": reward_points,
                "category_id": category_id,
                "recurring": recurring,
                "recurrence_set": recurrence_set,
                "recurring_until": recurring_until,
                "up_for_grabs": up_for_grabs,
                "emoji_icon": emoji_icon,
                "status": status,
                **(extra or {}),
            }
        )
        return self._request("POST", self._frame_path(frame_id, "/chores"), json=body)

    def create_chores(self, frame_id: str | int, chores: Any) -> Any:
        """Bulk-create chores. ``chores`` is the full request body (list or dict)."""
        return self._request(
            "POST", self._frame_path(frame_id, "/chores/create_multiple"), json=chores
        )

    def update_chore(self, frame_id: str | int, chore_id: str | int, **fields: Any) -> Any:
        return self._request(
            "PUT", self._frame_path(frame_id, f"/chores/{chore_id}"), json=_compact(fields)
        )

    def complete_chore(
        self,
        frame_id: str | int,
        chore_id: str | int,
        *,
        instance_date: Optional[str] = None,
        instance_time: Optional[str] = None,
        category_id: Optional[str | int] = None,
        status: str = "complete",
    ) -> Any:
        # Verified shape: PUT chores/{id}/completions {status, instance_date, instance_time,
        # category_id}; chore_id is the series id.
        body = _compact(
            {
                "status": status,
                "instance_date": instance_date,
                "instance_time": instance_time,
                "category_id": category_id,
            }
        )
        return self._request(
            "PUT", self._frame_path(frame_id, f"/chores/{chore_id}/completions"), json=body
        )

    def delete_chore(
        self, frame_id: str | int, chore_id: str | int, *, apply_to: Optional[str] = None
    ) -> None:
        params = {"apply_to": apply_to} if apply_to else None
        self._request("DELETE", self._frame_path(frame_id, f"/chores/{chore_id}"), params=params)

    # -- lists & list items (Tier 1) --------------------------------------

    def create_list(
        self,
        frame_id: str | int,
        label: str,
        *,
        color: Optional[str] = None,
        kind: Optional[str] = None,
        hide_from_frame: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = _compact(
            {
                "label": label,
                "color": color,
                "kind": kind,
                "hide_from_frame": hide_from_frame,
                **(extra or {}),
            }
        )
        return self._request("POST", self._frame_path(frame_id, "/lists"), json=body)

    def update_list(self, frame_id: str | int, list_id: str | int, **fields: Any) -> Any:
        return self._request(
            "PUT", self._frame_path(frame_id, f"/lists/{list_id}"), json=_compact(fields)
        )

    def delete_list(self, frame_id: str | int, list_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/lists/{list_id}"))

    def update_list_item(
        self,
        frame_id: str | int,
        list_id: str | int,
        item_id: str | int,
        *,
        label: Optional[str] = None,
        status: Optional[str] = None,
        position: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = _compact({"label": label, "status": status, "position": position, **(extra or {})})
        return self._request(
            "PUT",
            self._frame_path(frame_id, f"/lists/{list_id}/list_items/{item_id}"),
            json=body,
        )

    def complete_list_item(
        self, frame_id: str | int, list_id: str | int, item_id: str | int, *, completed: bool = True
    ) -> Any:
        return self.update_list_item(
            frame_id, list_id, item_id, status="completed" if completed else "pending"
        )

    def delete_list_item(self, frame_id: str | int, list_id: str | int, item_id: str | int) -> None:
        self._request(
            "DELETE", self._frame_path(frame_id, f"/lists/{list_id}/list_items/{item_id}")
        )

    def delete_list_items(
        self, frame_id: str | int, list_id: str | int, ids: List[str | int]
    ) -> Any:
        return self._request(
            "DELETE",
            self._frame_path(frame_id, f"/lists/{list_id}/list_items/bulk_destroy"),
            json={"ids": list(ids)},
        )

    def move_list_item(
        self,
        frame_id: str | int,
        list_id: str | int,
        item_id: str | int,
        *,
        after_item_id: Optional[str | int] = None,
    ) -> Any:
        return self._request(
            "POST",
            self._frame_path(frame_id, f"/lists/{list_id}/list_items/{item_id}/move"),
            json={"after_item_id": after_item_id},
        )

    def set_list_items_section(
        self, frame_id: str | int, list_id: str | int, item_ids: List[str | int], section: str
    ) -> Any:
        return self._request(
            "PUT",
            self._frame_path(frame_id, f"/lists/{list_id}/list_items/bulk_update_section"),
            json={"item_ids": list(item_ids), "section": section},
        )

    # -- categories / profiles (Tier 1) -----------------------------------

    def create_category(
        self,
        frame_id: str | int,
        label: str,
        color: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = _compact({"label": label, "color": color, **(extra or {})})
        return self._request("POST", self._frame_path(frame_id, "/categories"), json=body)

    def find_or_create_category(self, frame_id: str | int, label: str, color: str) -> Any:
        return self._request(
            "POST",
            self._frame_path(frame_id, "/categories/find_or_create"),
            json={"label": label, "color": color},
        )

    def update_category(self, frame_id: str | int, category_id: str | int, **fields: Any) -> Any:
        return self._request(
            "PATCH",
            self._frame_path(frame_id, f"/categories/{category_id}"),
            json=_compact(fields),
        )

    def delete_category(
        self,
        frame_id: str | int,
        category_id: str | int,
        *,
        reassign_to_id: Optional[str | int] = None,
    ) -> None:
        params = {"reassign_to_id": reassign_to_id} if reassign_to_id else None
        self._request(
            "DELETE", self._frame_path(frame_id, f"/categories/{category_id}"), params=params
        )

    # -- sitting instances (Tier 1) ---------------------------------------

    def list_sitting_instances(
        self,
        frame_id: str | int,
        sitting_id: str | int,
        *,
        date_min: Optional[str] = None,
        date_max: Optional[str] = None,
        include: Optional[str] = None,
    ) -> Any:
        params = _compact({"date_min": date_min, "date_max": date_max, "include": include}) or None
        return self._data(
            self._request(
                "GET",
                self._frame_path(frame_id, f"/meals/sittings/{sitting_id}/instances"),
                params=params,
            )
        )

    def update_sitting_instance(
        self,
        frame_id: str | int,
        sitting_id: str | int,
        date_iso: str,
        *,
        meal_recipe_id: Optional[str | int] = None,
        meal_category_id: Optional[str | int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = _compact(
            {
                "meal_recipe_id": meal_recipe_id,
                "meal_category_id": meal_category_id,
                **(extra or {}),
            }
        )
        return self._request(
            "PATCH",
            self._frame_path(frame_id, f"/meals/sittings/{sitting_id}/instances/{date_iso}"),
            json=body,
        )

    # -- calendar integration (Tier 2) -----------------------------------

    def list_calendars(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/calendars"))

    def get_calendar_account(self, frame_id: str | int, account_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/calendars/{account_id}"))

    def update_calendar_account(
        self, frame_id: str | int, account_id: str | int, active_calendars: List[Any]
    ) -> Any:
        return self._request(
            "PUT",
            self._frame_path(frame_id, f"/calendars/{account_id}"),
            json={"active_calendars": list(active_calendars)},
        )

    def calendar_authorization_url(
        self,
        frame_id: str | int,
        *,
        redirect_url: str,
        failure_redirect_url: str,
        two_way_sync: Optional[bool] = None,
        provider: Optional[str] = None,
        login_hint: Optional[str] = None,
    ) -> Any:
        params = _compact(
            {
                "redirect_url": redirect_url,
                "failure_redirect_url": failure_redirect_url,
                "two_way_sync": two_way_sync,
                "provider": provider,
                "login_hint": login_hint,
            }
        )
        return self._request(
            "GET", self._frame_path(frame_id, "/calendars/authorization_request_url"), params=params
        )

    def list_webcal_accounts(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/webcal_accounts"))

    def subscribe_webcal(self, frame_id: str | int, sync_url: str) -> Any:
        return self._request(
            "POST", self._frame_path(frame_id, "/webcal_accounts"), json={"sync_url": sync_url}
        )

    def list_source_calendars(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/source_calendars"))

    def get_source_calendar(self, frame_id: str | int, calendar_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/source_calendars/{calendar_id}"))

    # Note: there is no manual "create source calendar" endpoint (POST 404s live).
    # Source calendars are added by linking an account via calendar_authorization_url().

    def update_source_calendar(
        self, frame_id: str | int, calendar_id: str | int, **body: Any
    ) -> Any:
        return self._request(
            "PUT",
            self._frame_path(frame_id, f"/source_calendars/{calendar_id}"),
            json=_compact(body),
        )

    def delete_source_calendar(self, frame_id: str | int, calendar_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/source_calendars/{calendar_id}"))

    def set_default_source_calendar(self, frame_id: str | int, calendar_id: str | int) -> Any:
        return self._request(
            "POST",
            self._frame_path(frame_id, "/source_calendars/set_default_for_new_events"),
            json={"id": calendar_id},
        )

    def search_calendar_events(
        self, frame_id: str | int, search_query: str, *, timezone: Optional[str] = None
    ) -> Any:
        params = _compact({"search_query": search_query, "timezone": timezone})
        return self._request(
            "GET", self._frame_path(frame_id, "/calendar_events/search"), params=params
        )

    def list_countdowns(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/calendar_events/countdowns"))

    def recent_invited_emails(self, frame_id: str | int) -> Any:
        return self._request(
            "GET", self._frame_path(frame_id, "/calendar_events/recent_invited_emails")
        )

    def get_event_notification_settings(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/event_notification_settings"))

    def update_event_notification_settings(self, frame_id: str | int, **body: Any) -> Any:
        return self._request(
            "PUT", self._frame_path(frame_id, "/event_notification_settings"), json=_compact(body)
        )

    def get_reminder_notification(self) -> Any:
        # Verified: account-level "reminder profile" (not frame-scoped).
        return self._request("GET", f"{API_PREFIX}/reminder_profile")

    def update_reminder_notification(self, interval_weeks: int) -> Any:
        return self._request(
            "PUT", f"{API_PREFIX}/reminder_profile", json={"interval_weeks": interval_weeks}
        )

    def set_source_calendar_categorizations(
        self, frame_id: str | int, calendar_id: str | int, categorizations: Any
    ) -> Any:
        return self._request(
            "PUT",
            self._frame_path(
                frame_id, f"/source_calendars/{calendar_id}/source_calendar_categorizations"
            ),
            json={"categorizations": categorizations},
        )

    def set_category_source_calendar_categorizations(
        self, frame_id: str | int, category_id: str | int, categorizations: Any
    ) -> Any:
        return self._request(
            "PUT",
            self._frame_path(
                frame_id, f"/categories/{category_id}/source_calendar_categorizations"
            ),
            json={"categorizations": categorizations},
        )

    def list_task_box_items(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/task_box/items"))

    def create_task_box_item(self, frame_id: str | int, title: str, **extra: Any) -> Any:
        # Verified: the web client posts the item object flat (no task_box_item wrapper).
        return self._request(
            "POST",
            self._frame_path(frame_id, "/task_box/items"),
            json=_compact({"title": title, **extra}),
        )

    def update_task_box_item(self, frame_id: str | int, item_id: str | int, **body: Any) -> Any:
        return self._request(
            "PATCH", self._frame_path(frame_id, f"/task_box/items/{item_id}"), json=_compact(body)
        )

    def delete_task_box_item(self, frame_id: str | int, item_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/task_box/items/{item_id}"))

    def list_routines(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/routines"))

    def create_routine(
        self, frame_id: str | int, title: str, assignee_id: str | int, steps: Any, **extra: Any
    ) -> Any:
        body = _compact({"title": title, "assignee_id": assignee_id, "steps": steps, **extra})
        return self._request("POST", self._frame_path(frame_id, "/routines"), json=body)

    def update_routine(self, frame_id: str | int, routine_id: str | int, **fields: Any) -> Any:
        return self._request(
            "PUT", self._frame_path(frame_id, f"/routines/{routine_id}"), json=_compact(fields)
        )

    def delete_routine(self, frame_id: str | int, routine_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/routines/{routine_id}"))

    def reorder_routines(self, frame_id: str | int, ids: List[str | int]) -> Any:
        return self._request(
            "PATCH", self._frame_path(frame_id, "/routines/reorder"), json={"ids": list(ids)}
        )

    # -- rewards (Tier 3) -------------------------------------------------

    def list_rewards(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/rewards"))

    def get_reward(self, frame_id: str | int, reward_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/rewards/{reward_id}"))

    def create_reward(
        self,
        frame_id: str | int,
        name: str,
        point_value: int,
        *,
        category_ids: Optional[List[str | int]] = None,
        emoji_icon: Optional[str] = None,
        description: Optional[str] = None,
        respawn_on_redemption: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = _compact(
            {
                "name": name,
                "point_value": point_value,
                "category_ids": list(category_ids) if category_ids else None,
                "emoji_icon": emoji_icon,
                "description": description,
                "respawn_on_redemption": respawn_on_redemption,
                **(extra or {}),
            }
        )
        return self._request("POST", self._frame_path(frame_id, "/rewards"), json=body)

    def update_reward(self, frame_id: str | int, reward_id: str | int, **fields: Any) -> Any:
        return self._request(
            "PATCH", self._frame_path(frame_id, f"/rewards/{reward_id}"), json=_compact(fields)
        )

    def delete_reward(self, frame_id: str | int, reward_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/rewards/{reward_id}"))

    def redeem_reward(self, frame_id: str | int, reward_id: str | int) -> Any:
        return self._request("POST", self._frame_path(frame_id, f"/rewards/{reward_id}/redeem"))

    def unredeem_reward(self, frame_id: str | int, reward_id: str | int) -> Any:
        return self._request("POST", self._frame_path(frame_id, f"/rewards/{reward_id}/unredeem"))

    def get_reward_points(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/reward_points"))

    def set_reward_points(
        self, frame_id: str | int, category_ids: List[str | int], points: int
    ) -> Any:
        return self._request(
            "POST",
            self._frame_path(frame_id, "/reward_points"),
            json={"category_ids": list(category_ids), "points": points},
        )

    # -- messages / photos (Tier 3) --------------------------------------

    def list_messages(self, frame_id: str | int, **params: Any) -> Any:
        return self._request(
            "GET", self._frame_path(frame_id, "/messages"), params=_compact(params) or None
        )

    def get_message(self, frame_id: str | int, message_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/messages/{message_id}"))

    def delete_message(self, frame_id: str | int, message_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/messages/{message_id}"))

    def delete_messages(self, frame_id: str | int, message_ids: List[str | int]) -> Any:
        return self._request(
            "DELETE",
            self._frame_path(frame_id, "/messages/destroy_multiple"),
            json={"message_ids": list(message_ids)},
        )

    def copy_messages_to_frames(
        self, frame_id: str | int, message_ids: List[str | int], new_frame_ids: List[str | int]
    ) -> Any:
        return self._request(
            "POST",
            self._frame_path(frame_id, "/copy_to_frames"),
            json={"message_ids": list(message_ids), "new_frame_ids": list(new_frame_ids)},
        )

    def set_message_caption(self, frame_id: str | int, message_id: str | int, caption: str) -> Any:
        return self._request(
            "PUT",
            self._frame_path(frame_id, f"/messages/{message_id}/caption"),
            json={"caption": caption},
        )

    def list_message_likes(self, frame_id: str | int, message_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/messages/{message_id}/all_likes"))

    def like_message(self, frame_id: str | int, message_id: str | int) -> Any:
        return self._request("POST", self._frame_path(frame_id, f"/messages/{message_id}/likes"))

    def unlike_message(self, frame_id: str | int, message_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/messages/{message_id}/likes"))

    def list_message_comments(self, frame_id: str | int, message_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/messages/{message_id}/comments"))

    def comment_message(self, frame_id: str | int, message_id: str | int, body: str) -> Any:
        return self._request(
            "POST",
            self._frame_path(frame_id, f"/messages/{message_id}/comments"),
            json={"body": body},
        )

    def delete_message_comment(
        self, frame_id: str | int, message_id: str | int, comment_id: str | int
    ) -> None:
        self._request(
            "DELETE", self._frame_path(frame_id, f"/messages/{message_id}/comments/{comment_id}")
        )

    # -- albums (Tier 3) --------------------------------------------------

    def list_albums(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/albums"))

    def create_album(self, frame_id: str | int, title: str, **extra: Any) -> Any:
        return self._request(
            "POST", self._frame_path(frame_id, "/albums"), json=_compact({"title": title, **extra})
        )

    def update_album(self, frame_id: str | int, album_id: str | int, title: str) -> Any:
        return self._request(
            "PUT", self._frame_path(frame_id, f"/albums/{album_id}"), json={"title": title}
        )

    def delete_album(self, frame_id: str | int, album_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/albums/{album_id}"))

    def list_album_messages(self, frame_id: str | int, album_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/albums/{album_id}/messages"))

    def list_album_message_ids(self, frame_id: str | int, album_id: str | int) -> Any:
        return self._request(
            "GET", self._frame_path(frame_id, f"/albums/{album_id}/messages/all_ids")
        )

    def add_to_albums(
        self, frame_id: str | int, album_ids: List[str | int], message_ids: List[str | int]
    ) -> Any:
        return self._request(
            "POST",
            self._frame_path(frame_id, "/albums/add_to"),
            json={"album_ids": list(album_ids), "message_ids": list(message_ids)},
        )

    def remove_from_albums(
        self, frame_id: str | int, album_ids: List[str | int], message_ids: List[str | int]
    ) -> Any:
        return self._request(
            "POST",
            self._frame_path(frame_id, "/albums/remove_from"),
            json={"album_ids": list(album_ids), "message_ids": list(message_ids)},
        )

    # -- month in review, global reference reads, uploads (Tier 3) --------

    def month_in_review(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/month_in_review"))

    def list_month_in_reviews(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/month_in_reviews"))

    def list_avatars(self) -> Any:
        return self._request("GET", f"{API_PREFIX}/avatars")

    def list_colors(self) -> Any:
        return self._request("GET", f"{API_PREFIX}/colors")

    def list_activities(self) -> Any:
        return self._request("GET", f"{API_PREFIX}/activities")

    def cloud_upload_credentials(self) -> Any:
        return self._request("GET", f"{API_PREFIX}/messages/cloud_upload_credentials")

    def request_upload_url(
        self,
        *,
        ext: str,
        frame_ids: Optional[List[str | int]] = None,
        caption: Optional[str] = None,
        trim_start: Optional[float] = None,
        trim_end: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = _compact(
            {
                "ext": ext,
                "frame_ids": list(frame_ids) if frame_ids else None,
                "caption": caption,
                "trim_start": trim_start,
                "trim_end": trim_end,
                **(extra or {}),
            }
        )
        return self._request("POST", f"{API_PREFIX}/upload_url", json=body)

    def upload_photo(
        self,
        frame_id: str | int,
        file_path: str,
        *,
        caption: Optional[str] = None,
        ext: Optional[str] = None,
        trim_start: Optional[float] = None,
        trim_end: Optional[float] = None,
    ) -> Any:
        """Two-step photo upload: presign, then PUT bytes. Response shape unverified."""
        import os

        if ext is None:
            ext = os.path.splitext(file_path)[1].lstrip(".") or "jpg"
        presign = self.request_upload_url(
            ext=ext, frame_ids=[frame_id], caption=caption, trim_start=trim_start, trim_end=trim_end
        )
        data = presign.get("data") if isinstance(presign, dict) else None
        attrs = (data or presign or {}) if isinstance(presign, dict) else {}
        if isinstance(data, dict):
            attrs = data.get("attributes") or data
        upload_url = (
            attrs.get("upload_url") or attrs.get("url") if isinstance(attrs, dict) else None
        )
        if not upload_url:
            return presign
        with open(file_path, "rb") as fh:
            self._http.put(upload_url, content=fh.read())
        return presign

    # -- devices & alarms (Tier 4) ----------------------------------------

    def list_devices(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/devices"))

    def get_device(self, frame_id: str | int, device_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/devices/{device_id}"))

    def update_device(self, frame_id: str | int, device_id: str | int, **body: Any) -> Any:
        return self._request(
            "PUT", self._frame_path(frame_id, f"/devices/{device_id}"), json=_compact(body)
        )

    def delete_device(self, frame_id: str | int, device_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/devices/{device_id}"))

    def device_activation_code(self, frame_id: str | int, device_id: str | int) -> Any:
        return self._request(
            "POST", self._frame_path(frame_id, f"/devices/{device_id}/activation_code")
        )

    def reset_device(self, frame_id: str | int, device_id: str | int) -> Any:
        return self._request("POST", self._frame_path(frame_id, f"/devices/{device_id}/reset"))

    def list_alarms(self, frame_id: str | int, device_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, f"/devices/{device_id}/alarms"))

    def create_alarm(self, frame_id: str | int, device_id: str | int, **body: Any) -> Any:
        return self._request(
            "POST", self._frame_path(frame_id, f"/devices/{device_id}/alarms"), json=_compact(body)
        )

    def update_alarm(
        self, frame_id: str | int, device_id: str | int, alarm_id: str | int, **body: Any
    ) -> Any:
        return self._request(
            "PATCH",
            self._frame_path(frame_id, f"/devices/{device_id}/alarms/{alarm_id}"),
            json=_compact(body),
        )

    def delete_alarm(self, frame_id: str | int, device_id: str | int, alarm_id: str | int) -> None:
        self._request(
            "DELETE", self._frame_path(frame_id, f"/devices/{device_id}/alarms/{alarm_id}")
        )

    # -- household members & config (Tier 4) ------------------------------

    def list_frame_users(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/users"))

    def invite_frame_user(self, frame_id: str | int, email: str) -> Any:
        return self._request("POST", self._frame_path(frame_id, "/users"), json={"email": email})

    def approve_frame_user(self, frame_id: str | int, user_id: str | int) -> Any:
        return self._request("POST", self._frame_path(frame_id, f"/users/{user_id}/approve"))

    def remove_frame_user(self, frame_id: str | int, user_id: str | int) -> None:
        self._request("DELETE", self._frame_path(frame_id, f"/users/{user_id}"))

    def update_family_member(
        self, frame_id: str | int, category_id: str | int, **fields: Any
    ) -> Any:
        # Verified: the web client edits a profile's family-member info via the category
        # sub-resource: PUT categories/{categoryId}/family_member.
        return self._request(
            "PUT",
            self._frame_path(frame_id, f"/categories/{category_id}/family_member"),
            json=_compact(fields),
        )

    def get_household_config(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/household_config"))

    def update_household_config(self, frame_id: str | int, **body: Any) -> Any:
        return self._request(
            "PATCH", self._frame_path(frame_id, "/household_config"), json=_compact(body)
        )

    # -- environment / misc (Tier 4) --------------------------------------

    def get_weather(self, **params: Any) -> Any:
        return self._request("GET", f"{API_PREFIX}/weather", params=_compact(params) or None)

    def get_geolocation(self, **params: Any) -> Any:
        return self._request("GET", f"{API_PREFIX}/geolocation", params=_compact(params) or None)

    def generate_one_link(self, **body: Any) -> Any:
        return self._request("POST", f"{API_PREFIX}/generate_one_link", json=_compact(body))

    def list_plus_subscriptions(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/plus/subscriptions"))

    # -- frame management (Tier 4) ----------------------------------------

    def frame_rename(self, frame_id: str | int, name: str) -> Any:
        return self._request("PUT", self._frame_path(frame_id, "/rename"), json={"name": name})

    def update_frame_settings(self, frame_id: str | int, **fields: Any) -> Any:
        return self._request("PUT", f"{API_PREFIX}/frames/{frame_id}", json=_compact(fields))

    def update_frame_timezone(self, frame_id: str | int, timezone: str) -> Any:
        return self._request(
            "PATCH", f"{API_PREFIX}/frames/{frame_id}", json={"timezone": timezone}
        )

    def hide_frame(self, frame_id: str | int) -> Any:
        return self._request("POST", self._frame_path(frame_id, "/hide"))

    def frame_activation_code(self, frame_id: str | int) -> Any:
        return self._request("POST", self._frame_path(frame_id, "/activation_code"))

    # -- AI Sidekick / auto-creation intents (Tier 5) ---------------------

    def list_auto_creation_intents(self, frame_id: str | int) -> Any:
        return self._request("GET", self._frame_path(frame_id, "/auto_creation_intents"))

    def get_auto_creation_intent(self, frame_id: str | int, intent_id: str | int) -> Any:
        return self._request(
            "GET", self._frame_path(frame_id, f"/auto_creation_intents/{intent_id}")
        )

    def create_auto_creation_intent(
        self,
        frame_id: str | int,
        *,
        text: Optional[str] = None,
        engine: Optional[str] = None,
        created_via: Optional[str] = None,
        draft_first: Optional[bool] = None,
        list_id: Optional[str | int] = None,
        meal_category_id: Optional[str | int] = None,
        content_url: Optional[str] = None,
        ext: Optional[str] = None,
        **extra: Any,
    ) -> Any:
        # Verified: the web client posts {ext, engine, text, created_via, draft_first} plus
        # a type-specific target (list_id | meal_category_id+content_url | …). No "type" field.
        body = _compact(
            {
                "ext": ext,
                "engine": engine,
                "text": text,
                "created_via": created_via,
                "draft_first": draft_first,
                "list_id": list_id,
                "meal_category_id": meal_category_id,
                "content_url": content_url,
                **extra,
            }
        )
        return self._request(
            "POST", self._frame_path(frame_id, "/auto_creation_intents"), json=body
        )

    def approve_auto_creation_intent(self, frame_id: str | int, intent_id: str | int) -> Any:
        return self._request(
            "POST", self._frame_path(frame_id, f"/auto_creation_intents/{intent_id}/approve_draft")
        )

    def retry_auto_creation_intent(self, frame_id: str | int, intent_id: str | int) -> Any:
        return self._request(
            "POST", self._frame_path(frame_id, f"/auto_creation_intents/{intent_id}/retry_draft")
        )

    def undo_auto_creation_intent(self, frame_id: str | int, intent_id: str | int) -> Any:
        return self._request(
            "POST", self._frame_path(frame_id, f"/auto_creation_intents/{intent_id}/undo")
        )

    def auto_creation_intent_items(self, frame_id: str | int, intent_id: str | int) -> Any:
        return self._request(
            "GET", self._frame_path(frame_id, f"/auto_creation_intents/{intent_id}/created_items")
        )
