"""Constant values for the Skylight private API.

These are derived from community reverse-engineering of the Skylight Calendar /
Frame / Buddy apps (notably bryanmig/skylight-calendar-api and
kylebjordahl/skylight-calendar-home-assistant). The API is **unofficial** and may
change without notice.
"""

from __future__ import annotations

#: Base host for the Skylight app/mobile API. Data endpoints live under ``/api``.
DEFAULT_BASE_URL = "https://app.ourskylight.com"

#: Path prefix for the JSON:API data endpoints.
API_PREFIX = "/api"

#: Default per-request timeout (seconds).
DEFAULT_TIMEOUT = 30.0

#: A stable, honest user agent for data (API) requests.
USER_AGENT = "pyskylight (+https://github.com/joshuaswarren/pyskylight)"

#: The web OAuth login pages are served to browsers; present a browser UA there.
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# --- Modern OAuth2 (PKCE) constants, for the optional app-equivalent login flow.
# Reported by kylejfrost/skylight-api-cli; not used by the default legacy login.
OAUTH_CLIENT_ID = "skylight-mobile"
OAUTH_SCOPE = "everything"
OAUTH_REDIRECT_URI = "skylight-family://welcome"
OAUTH_CODE_CHALLENGE_METHOD = "S256"
