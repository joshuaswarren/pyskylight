"""Tests for sitting update/delete (added for the sync use case)."""

from __future__ import annotations

import respx
from httpx import Response

from pyskylight import Credentials, SkylightClient
from pyskylight.constants import API_PREFIX, DEFAULT_BASE_URL

BASE = DEFAULT_BASE_URL


def _client() -> SkylightClient:
    return SkylightClient(Credentials("123", "tok"))


@respx.mock
def test_update_sitting_uses_patch():
    route = respx.patch(f"{BASE}{API_PREFIX}/frames/7/meals/sittings/5").mock(
        return_value=Response(200, json={"data": {"id": "5", "attributes": {"date": "2026-06-20"}}})
    )
    s = _client().update_sitting("7", "5", meal_recipe_id="9")
    assert s.id == "5"
    assert route.called


@respx.mock
def test_delete_sitting():
    route = respx.delete(f"{BASE}{API_PREFIX}/frames/7/meals/sittings/5/instances/2026-06-20").mock(
        return_value=Response(204)
    )
    assert _client().delete_sitting("7", "5", "2026-06-20") is None
    assert route.called
