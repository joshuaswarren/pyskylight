"""pyskylight — an unofficial Python client + CLI for the Skylight Calendar API.

Skylight has no official/public API; this wraps the private app API that the
community has reverse-engineered. For personal use against your own account only.
"""

from __future__ import annotations

from .auth import Credentials, login
from .client import SkylightClient
from .constants import DEFAULT_BASE_URL
from .errors import (
    SkylightAPIError,
    SkylightAuthError,
    SkylightError,
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
    Resource,
    Sitting,
)

__version__ = "0.3.2"

__all__ = [
    "__version__",
    "DEFAULT_BASE_URL",
    "SkylightClient",
    "Credentials",
    "login",
    "SkylightError",
    "SkylightAuthError",
    "SkylightPlusRequiredError",
    "SkylightNotFoundError",
    "SkylightRateLimitError",
    "SkylightAPIError",
    "Resource",
    "Frame",
    "Category",
    "CalendarEvent",
    "MealCategory",
    "Recipe",
    "Sitting",
]
