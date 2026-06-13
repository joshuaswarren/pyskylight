# pyskylight

Unofficial Python client and `skylight` CLI for the [Skylight Calendar](https://www.skylightframe.com/)
/ Buddy family of devices.

Skylight has **no official or public API.** This library talks to the same private
app API (`app.ourskylight.com`) that the community has reverse-engineered. It is for
**personal use against your own account** — see [Legal](#legal).

## Features

- Email/password login (legacy Basic-token flow) with on-disk token caching.
- Typed client for frames, calendar events, categories, lists, chores, and **Meals**
  (recipes + planned "sittings").
- A JSON-first `skylight` CLI suitable for scripting or driving from an agent.
- 1Password-friendly: credentials may be `op://` references resolved at runtime.

## Install

```bash
pip install pyskylight        # once published
# or from source:
pip install -e ".[dev]"
```

Requires Python 3.11+.

## Quick start

### CLI

```bash
export SKYLIGHT_EMAIL="you@example.com"
export SKYLIGHT_PASSWORD="…"          # or an op:// reference

skylight login                         # caches the session token
skylight frames                        # find your frame (household) id
export SKYLIGHT_FRAME_ID=123456

skylight meal-categories               # Breakfast / Lunch / Dinner ids
skylight recipes                       # list recipes
skylight create-recipe --summary "Tacos" --description "Tuesday classic"
skylight plan-add --date 2026-06-20 --meal-category-id 42 --recipe-id 99
```

Every command prints JSON.

### Library

```python
from pyskylight import SkylightClient

with SkylightClient.login("you@example.com", "…") as sky:
    frame = sky.list_frames()[0]
    for recipe in sky.list_recipes(frame.id):
        print(recipe.id, recipe.summary)
    sky.create_sitting(frame.id, date="2026-06-20", meal_category_id="42", meal_recipe_id="99")
```

## Configuration

| Variable | Purpose |
|---|---|
| `SKYLIGHT_EMAIL` | account email (or `op://vault/item/field`) |
| `SKYLIGHT_PASSWORD` | account password (or `op://…`) |
| `SKYLIGHT_FRAME_ID` | default frame id, so `--frame` is optional |
| `SKYLIGHT_TIMEZONE` | default IANA timezone for calendar queries |
| `SKYLIGHT_BASE_URL` | override the API base URL |

The session token is cached at `${XDG_CACHE_HOME:-~/.cache}/pyskylight/token.json`
(mode `0600`). `skylight logout` clears it.

## Authentication notes

Login posts to `POST /api/sessions` and stores `user_id` + `token`; subsequent
requests send `Authorization: Basic base64(user_id:token)`. The client
re-authenticates automatically when the token expires (HTTP 401).

> **Skylight Plus:** the Meals/Recipes features appear to require an active Skylight
> Plus subscription. Without it those endpoints return HTTP 403, surfaced as
> `SkylightPlusRequiredError`.

## Development

```bash
pip install -e ".[dev]"
pytest                      # full suite + coverage (fails under 90%)
pre-commit run --all-files  # black, isort, flake8, mypy
```

## Related projects

- **openclaw-skylight** — an OpenClaw skill that drives this CLI.
- **plantoeat-skylight-sync** — syncs a Plan to Eat meal plan into Skylight Meals.

Prior art that informed this client: [bryanmig/skylight-calendar-api](https://github.com/bryanmig/skylight-calendar-api),
[kylebjordahl/skylight-calendar-home-assistant](https://github.com/kylebjordahl/skylight-calendar-home-assistant),
and [kylejfrost/skylight-api-cli](https://github.com/kylejfrost/skylight-api-cli).

## Legal

Unofficial and not affiliated with, endorsed by, or supported by Skylight. The API
can change without notice. Use only with your own account and data; do not build a
multi-tenant or commercial service on it. Provided as-is under the [MIT License](LICENSE).
