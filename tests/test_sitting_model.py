"""Sitting date parsing (instances list vs flat date)."""

from __future__ import annotations

from pyskylight.models import Sitting


def test_date_and_dates_from_instances():
    s = Sitting.from_jsonapi({"id": "1", "attributes": {"instances": ["2026-06-13", "2026-06-20"]}})
    assert s.date == "2026-06-13"
    assert s.dates == ["2026-06-13", "2026-06-20"]


def test_date_falls_back_to_flat_field():
    s = Sitting.from_jsonapi({"id": "1", "attributes": {"date": "2026-06-21"}})
    assert s.date == "2026-06-21"
    assert s.dates == ["2026-06-21"]


def test_no_date():
    s = Sitting.from_jsonapi({"id": "1", "attributes": {}})
    assert s.date is None
    assert s.dates == []
