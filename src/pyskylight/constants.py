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

#: A desktop-ish user agent. The API does not appear to require a specific one,
#: but a stable, honest UA is good manners against a Cloudflare-fronted service.
USER_AGENT = "pyskylight (+https://github.com/joshuaswarren/pyskylight)"

# --- Modern OAuth2 (PKCE) constants, for the optional app-equivalent login flow.
# Reported by kylejfrost/skylight-api-cli; not used by the default legacy login.
OAUTH_CLIENT_ID = "skylight-mobile"
OAUTH_SCOPE = "everything"
OAUTH_REDIRECT_URI = "skylight-family://welcome"
OAUTH_CODE_CHALLENGE_METHOD = "S256"
