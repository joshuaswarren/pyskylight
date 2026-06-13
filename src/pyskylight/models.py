"""Lightweight typed wrappers over the Skylight JSON:API resources.

Skylight responses follow JSON:API: ``{"data": {"id", "type", "attributes", ...}}``
(or a list of those under ``data``). Because the exact attribute schema is only
partially documented and may change, every model keeps the raw ``attributes`` dict
and exposes convenience accessors on top. Unknown fields are never lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Self, TypeVar


@dataclass
class Resource:
    """A generic JSON:API resource object."""

    id: str
    type: str
    attributes: Dict[str, Any] = field(default_factory=dict)
    relationships: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_jsonapi(cls, data: Dict[str, Any]) -> "Self":
        return cls(
            id=str(data.get("id", "")),
            type=str(data.get("type", "")),
            attributes=dict(data.get("attributes") or {}),
            relationships=dict(data.get("relationships") or {}),
        )

    def attr(self, name: str, default: Any = None) -> Any:
        """Return an attribute value, or ``default`` if absent."""
        return self.attributes.get(name, default)

    def related_id(self, name: str) -> str | None:
        """Return the id of a to-one relationship, if present."""
        rel = self.relationships.get(name) or {}
        rel_data = rel.get("data") or {}
        rid = rel_data.get("id")
        return str(rid) if rid is not None else None


@dataclass
class Frame(Resource):
    """A Skylight "frame" — i.e. one household/device group."""

    @property
    def name(self) -> str | None:
        return self.attr("name") or self.attr("label")


@dataclass
class Category(Resource):
    """A family-member profile / color category."""

    @property
    def label(self) -> str | None:
        return self.attr("label")

    @property
    def color(self) -> str | None:
        return self.attr("color")


@dataclass
class CalendarEvent(Resource):
    @property
    def summary(self) -> str | None:
        return self.attr("summary")

    @property
    def starts_at(self) -> str | None:
        return self.attr("starts_at")

    @property
    def ends_at(self) -> str | None:
        return self.attr("ends_at")

    @property
    def all_day(self) -> bool:
        return bool(self.attr("all_day", False))


@dataclass
class MealCategory(Resource):
    """A meal bucket, e.g. Breakfast / Lunch / Dinner / Snack."""

    @property
    def label(self) -> str | None:
        return self.attr("label") or self.attr("name")


@dataclass
class Recipe(Resource):
    @property
    def summary(self) -> str | None:
        return self.attr("summary")

    @property
    def description(self) -> str | None:
        return self.attr("description")

    @property
    def meal_category_id(self) -> str | None:
        return self.related_id("meal_category") or (
            str(self.attr("meal_category_id"))
            if self.attr("meal_category_id") is not None
            else None
        )


@dataclass
class Sitting(Resource):
    """A planned meal: a date + meal category, optionally pointing at a recipe."""

    @property
    def date(self) -> str | None:
        # A sitting carries its date(s) in ``attributes.instances`` (a list of
        # ISO date strings); older/other shapes may use a flat ``date`` field.
        instances = self.attr("instances")
        if isinstance(instances, list) and instances:
            return str(instances[0])
        return self.attr("date")

    @property
    def dates(self) -> list[str]:
        instances = self.attr("instances")
        if isinstance(instances, list) and instances:
            return [str(d) for d in instances]
        single = self.attr("date")
        return [str(single)] if single else []

    @property
    def meal_category_id(self) -> str | None:
        return self.related_id("meal_category") or (
            str(self.attr("meal_category_id"))
            if self.attr("meal_category_id") is not None
            else None
        )

    @property
    def meal_recipe_id(self) -> str | None:
        return self.related_id("meal_recipe") or (
            str(self.attr("meal_recipe_id")) if self.attr("meal_recipe_id") is not None else None
        )


R = TypeVar("R", bound=Resource)


def parse_list(payload: Dict[str, Any], model: type[R]) -> List[R]:
    """Parse a JSON:API list payload (``{"data": [...]}``) into ``model`` objects."""
    items = payload.get("data") or []
    return [model.from_jsonapi(item) for item in items]


def parse_one(payload: Dict[str, Any], model: type[R]) -> R:
    """Parse a JSON:API single-object payload (``{"data": {...}}``)."""
    data = payload.get("data") or {}
    return model.from_jsonapi(data)
