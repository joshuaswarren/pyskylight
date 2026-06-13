"""Tests for SkylightClient."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from httpx import Response

from pyskylight import Credentials, SkylightClient
from pyskylight.constants import API_PREFIX, DEFAULT_BASE_URL
from pyskylight.errors import (
    SkylightAPIError,
    SkylightAuthError,
    SkylightNotFoundError,
    SkylightPlusRequiredError,
    SkylightRateLimitError,
)

BASE = DEFAULT_BASE_URL


def make_client() -> SkylightClient:
    return SkylightClient(Credentials("tok"))


@respx.mock
def test_login_classmethod_builds_client():
    holder = {}

    def on_auth(req):
        holder["s"] = parse_qs(urlparse(str(req.url)).query).get("state", [""])[0]
        return Response(200, html='<input name="authenticity_token" value="c">')

    respx.get(f"{BASE}/oauth/authorize").mock(side_effect=on_auth)
    respx.post(f"{BASE}/auth/session").mock(
        side_effect=lambda req: Response(
            302, headers={"Location": f"skylight-family://welcome?code=C&state={holder['s']}"}
        )
    )
    respx.post(f"{BASE}/oauth/token").mock(
        return_value=Response(
            200,
            json={
                "access_token": "AT",
                "refresh_token": "RT",
                "expires_in": 7200,
                "created_at": 1000,
            },
        )
    )
    client = SkylightClient.login("a@b.com", "pw")
    assert client.credentials.access_token == "AT"
    client.close()


@respx.mock
def test_list_frames_sends_auth_and_parses():
    route = respx.get(f"{BASE}{API_PREFIX}/frames").mock(
        return_value=Response(
            200, json={"data": [{"id": "7", "type": "frame", "attributes": {"name": "Home"}}]}
        )
    )
    frames = make_client().list_frames()
    assert frames[0].id == "7"
    assert frames[0].name == "Home"
    assert route.calls.last.request.headers["Authorization"].startswith("Bearer ")


@respx.mock
def test_list_frames_include_deleted_param():
    route = respx.get(f"{BASE}{API_PREFIX}/frames").mock(
        return_value=Response(200, json={"data": []})
    )
    make_client().list_frames(include_deleted=True)
    assert "show_deleted=true" in str(route.calls.last.request.url)


@respx.mock
def test_get_frame_and_user():
    respx.get(f"{BASE}{API_PREFIX}/frames/7").mock(
        return_value=Response(200, json={"data": {"id": "7", "type": "frame", "attributes": {}}})
    )
    respx.get(f"{BASE}{API_PREFIX}/user").mock(
        return_value=Response(200, json={"data": {"id": "1"}})
    )
    c = make_client()
    assert c.get_frame("7").id == "7"
    assert c.get_user() == {"data": {"id": "1"}}


@respx.mock
def test_calendar_events_params():
    route = respx.get(f"{BASE}{API_PREFIX}/frames/7/calendar_events").mock(
        return_value=Response(200, json={"data": []})
    )
    make_client().list_calendar_events(
        "7", "2026-06-01T00:00:00", "2026-06-30T00:00:00", "America/Chicago", include="category"
    )
    url = str(route.calls.last.request.url)
    assert (
        "date_min=" in url
        and "date_max=" in url
        and "timezone=America" in url
        and "include=category" in url
    )


@respx.mock
def test_create_calendar_event_body():
    route = respx.post(f"{BASE}{API_PREFIX}/frames/7/calendar_events").mock(
        return_value=Response(
            201,
            json={"data": {"id": "5", "type": "calendar_event", "attributes": {"summary": "x"}}},
        )
    )
    ev = make_client().create_calendar_event("7", "Dentist", all_day=True, category_ids=["1"])
    assert ev.id == "5"
    import json as _json

    body = _json.loads(route.calls.last.request.content)
    assert body == {"summary": "Dentist", "all_day": True, "category_ids": ["1"]}


@respx.mock
def test_update_and_delete_event():
    respx.put(f"{BASE}{API_PREFIX}/frames/7/calendar_events/5").mock(
        return_value=Response(200, json={"data": {"id": "5", "attributes": {}}})
    )
    delete = respx.delete(f"{BASE}{API_PREFIX}/frames/7/calendar_events/5").mock(
        return_value=Response(204)
    )
    c = make_client()
    c.update_calendar_event("7", "5", summary="New")
    assert c.delete_calendar_event("7", "5") is None
    assert delete.called


@respx.mock
def test_meal_categories_and_recipes():
    respx.get(f"{BASE}{API_PREFIX}/frames/7/meals/categories").mock(
        return_value=Response(200, json={"data": [{"id": "1", "attributes": {"label": "Dinner"}}]})
    )
    route = respx.get(f"{BASE}{API_PREFIX}/frames/7/meals/recipes").mock(
        return_value=Response(200, json={"data": [{"id": "9", "attributes": {"summary": "Tacos"}}]})
    )
    c = make_client()
    assert c.list_meal_categories("7")[0].label == "Dinner"
    assert c.list_recipes("7")[0].summary == "Tacos"
    assert "include=meal_category" in str(route.calls.last.request.url)


@respx.mock
def test_create_recipe_compacts_body():
    route = respx.post(f"{BASE}{API_PREFIX}/frames/7/meals/recipes").mock(
        return_value=Response(201, json={"data": {"id": "9", "attributes": {"summary": "Tacos"}}})
    )
    make_client().create_recipe("7", "Tacos", description=None, meal_category_id="3")
    import json as _json

    body = _json.loads(route.calls.last.request.content)
    assert body == {"summary": "Tacos", "meal_category_id": "3"}  # None dropped


@respx.mock
def test_update_recipe_uses_patch():
    route = respx.patch(f"{BASE}{API_PREFIX}/frames/7/meals/recipes/9").mock(
        return_value=Response(200, json={"data": {"id": "9", "attributes": {"summary": "New"}}})
    )
    make_client().update_recipe("7", "9", summary="New")
    assert route.called


@respx.mock
def test_get_delete_recipe_and_grocery():
    respx.get(f"{BASE}{API_PREFIX}/frames/7/meals/recipes/9").mock(
        return_value=Response(200, json={"data": {"id": "9", "attributes": {}}})
    )
    respx.delete(f"{BASE}{API_PREFIX}/frames/7/meals/recipes/9").mock(return_value=Response(204))
    grocery = respx.post(f"{BASE}{API_PREFIX}/frames/7/meals/recipes/9/add_to_grocery_list").mock(
        return_value=Response(200, json={"ok": True})
    )
    c = make_client()
    assert c.get_recipe("7", "9").id == "9"
    assert c.delete_recipe("7", "9") is None
    assert c.add_recipe_to_grocery_list("7", "9") == {"ok": True}
    assert grocery.called


@respx.mock
def test_sittings_list_and_create():
    respx.get(f"{BASE}{API_PREFIX}/frames/7/meals/sittings").mock(
        return_value=Response(
            200, json={"data": [{"id": "1", "attributes": {"date": "2026-06-20"}}]}
        )
    )
    route = respx.post(f"{BASE}{API_PREFIX}/frames/7/meals/sittings").mock(
        return_value=Response(
            201, json={"data": [{"id": "2", "attributes": {"instances": ["2026-06-21"]}}]}
        )
    )
    c = make_client()
    assert c.list_sittings("7", "2026-06-01", "2026-06-30")[0].date == "2026-06-20"
    s = c.create_sitting("7", "2026-06-21", "3", meal_recipe_id="9")
    assert s.id == "2"
    assert s.date == "2026-06-21"  # parsed from instances list
    import json as _json

    body = _json.loads(route.calls.last.request.content)
    assert body == {"date": "2026-06-21", "meal_category_id": "3", "meal_recipe_id": "9"}


@respx.mock
def test_lists_and_chores():
    respx.get(f"{BASE}{API_PREFIX}/frames/7/lists").mock(
        return_value=Response(
            200, json={"data": [{"id": "1", "attributes": {"label": "Groceries"}}]}
        )
    )
    additem = respx.post(f"{BASE}{API_PREFIX}/frames/7/lists/1/list_items").mock(
        return_value=Response(201, json={"data": {"id": "2"}})
    )
    respx.get(f"{BASE}{API_PREFIX}/frames/7/chores").mock(
        return_value=Response(200, json={"data": [{"id": "1"}]})
    )
    c = make_client()
    assert c.list_lists("7")[0]["id"] == "1"
    c.add_list_item("7", "1", "Milk", section="Dairy")
    assert additem.called
    assert c.list_chores("7", include_late="true")[0]["id"] == "1"


@respx.mock
@pytest.mark.parametrize(
    "status,exc",
    [
        (401, SkylightAuthError),
        (403, SkylightPlusRequiredError),
        (404, SkylightNotFoundError),
        (500, SkylightAPIError),
    ],
)
def test_error_mapping(status, exc):
    respx.get(f"{BASE}{API_PREFIX}/frames").mock(return_value=Response(status, text="err"))
    with pytest.raises(exc):
        make_client().list_frames()


@respx.mock
def test_rate_limit_retry_after():
    respx.get(f"{BASE}{API_PREFIX}/frames").mock(
        return_value=Response(429, headers={"Retry-After": "30"})
    )
    with pytest.raises(SkylightRateLimitError) as ei:
        make_client().list_frames()
    assert ei.value.retry_after == 30.0


@respx.mock
def test_rate_limit_bad_retry_after_header():
    respx.get(f"{BASE}{API_PREFIX}/frames").mock(
        return_value=Response(429, headers={"Retry-After": "soon"})
    )
    with pytest.raises(SkylightRateLimitError) as ei:
        make_client().list_frames()
    assert ei.value.retry_after is None


@respx.mock
def test_network_error_wrapped():
    respx.get(f"{BASE}{API_PREFIX}/frames").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(SkylightAPIError):
        make_client().list_frames()


@respx.mock
def test_empty_body_returns_none():
    respx.get(f"{BASE}{API_PREFIX}/user").mock(return_value=Response(200, content=b""))
    assert make_client().get_user() == {}


def test_context_manager_closes():
    with SkylightClient(Credentials("1", "t")) as c:
        assert isinstance(c, SkylightClient)
    # underlying client is closed; a second close is a no-op
    c.close()
