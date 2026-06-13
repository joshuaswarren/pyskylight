"""Tests for the exception hierarchy."""

from __future__ import annotations

from pyskylight.errors import (
    SkylightAPIError,
    SkylightAuthError,
    SkylightError,
    SkylightRateLimitError,
)


def test_subclassing():
    assert issubclass(SkylightAuthError, SkylightError)
    assert issubclass(SkylightRateLimitError, SkylightError)


def test_rate_limit_retry_after():
    err = SkylightRateLimitError("slow down", retry_after=12.0)
    assert err.retry_after == 12.0
    assert "slow down" in str(err)


def test_api_error_carries_context():
    err = SkylightAPIError("boom", status_code=500, body="oops")
    assert err.status_code == 500
    assert err.body == "oops"
