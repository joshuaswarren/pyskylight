"""Tests for the JSON:API model wrappers."""

from __future__ import annotations

from pyskylight.models import (
    Frame,
    MealCategory,
    Recipe,
    Resource,
    Sitting,
    parse_list,
    parse_one,
)


def test_resource_from_jsonapi_and_attr():
    r = Resource.from_jsonapi({"id": 5, "type": "thing", "attributes": {"a": 1}})
    assert r.id == "5"
    assert r.type == "thing"
    assert r.attr("a") == 1
    assert r.attr("missing", "default") == "default"


def test_related_id():
    r = Resource.from_jsonapi(
        {"id": "1", "type": "x", "relationships": {"cat": {"data": {"id": 9, "type": "category"}}}}
    )
    assert r.related_id("cat") == "9"
    assert r.related_id("nope") is None


def test_frame_name_falls_back_to_label():
    assert Frame.from_jsonapi({"id": "1", "attributes": {"label": "Home"}}).name == "Home"
    assert Frame.from_jsonapi({"id": "1", "attributes": {"name": "House"}}).name == "House"


def test_recipe_meal_category_from_relationship_and_attribute():
    via_rel = Recipe.from_jsonapi(
        {"id": "1", "relationships": {"meal_category": {"data": {"id": "7"}}}}
    )
    assert via_rel.meal_category_id == "7"
    via_attr = Recipe.from_jsonapi({"id": "2", "attributes": {"meal_category_id": 8}})
    assert via_attr.meal_category_id == "8"
    assert Recipe.from_jsonapi({"id": "3"}).meal_category_id is None


def test_recipe_summary_description():
    r = Recipe.from_jsonapi({"id": "1", "attributes": {"summary": "Tacos", "description": "yum"}})
    assert r.summary == "Tacos"
    assert r.description == "yum"


def test_sitting_properties():
    s = Sitting.from_jsonapi(
        {
            "id": "1",
            "attributes": {"date": "2026-06-20"},
            "relationships": {
                "meal_category": {"data": {"id": "3"}},
                "meal_recipe": {"data": {"id": "99"}},
            },
        }
    )
    assert s.date == "2026-06-20"
    assert s.meal_category_id == "3"
    assert s.meal_recipe_id == "99"


def test_meal_category_label():
    assert (
        MealCategory.from_jsonapi({"id": "1", "attributes": {"name": "Dinner"}}).label == "Dinner"
    )


def test_parse_helpers():
    items = parse_list({"data": [{"id": "1"}, {"id": "2"}]}, Frame)
    assert [f.id for f in items] == ["1", "2"]
    assert parse_list({}, Frame) == []
    one = parse_one({"data": {"id": "9"}}, Frame)
    assert one.id == "9"
