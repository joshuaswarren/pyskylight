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
        headers.setdefault("Authorization", self.credentials.basic_auth_header)
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
        return parse_one(payload or {}, Sitting)

    def update_sitting(self, frame_id: str | int, sitting_id: str | int, **fields: Any) -> Sitting:
        """Update a planned meal (PATCH). Verb/shape inferred; confirm against live traffic."""
        payload = self._request(
            "PATCH",
            f"{API_PREFIX}/frames/{frame_id}/meals/sittings/{sitting_id}",
            json=_compact(fields),
        )
        return parse_one(payload or {}, Sitting)

    def delete_sitting(self, frame_id: str | int, sitting_id: str | int) -> None:
        """Remove a planned meal. Path inferred (REST convention); confirm against live traffic."""
        self._request("DELETE", f"{API_PREFIX}/frames/{frame_id}/meals/sittings/{sitting_id}")

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
