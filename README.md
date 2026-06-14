# pyskylight

![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![status: alpha](https://img.shields.io/badge/status-alpha-orange)

Unofficial Python client and `skylight` CLI for the [Skylight Calendar](https://www.skylightframe.com/)
/ Buddy family of devices.

> Part of a three-repo set: **pyskylight** (client + CLI) ·
> [`openclaw-skylight`](https://github.com/joshuaswarren/openclaw-skylight) (OpenClaw skill) ·
> [`plantoeat-skylight-sync`](https://github.com/joshuaswarren/plantoeat-skylight-sync) (meal-plan sync).

Skylight has **no official or public API.** This library talks to the same private
app API (`app.ourskylight.com`) that the community has reverse-engineered. It is for
**personal use against your own account** — see [Legal](#legal).

## Features

- Email/password login via the app's OAuth2 (PKCE) flow, with token caching + refresh.
- **Near-complete coverage of the private API** — ~150 client methods / ~145 `skylight`
  CLI commands spanning frames, calendar (events, search, countdowns, connected/source
  calendars, webcal subscriptions, Google-link flow), **Meals** (recipes + planned
  "sittings" + instances), chores, lists & list items, categories/profiles, **rewards**,
  **photos/messages/albums**, month-in-review, **devices & Buddy alarms**, household
  members & config, routines, task-box, weather/geolocation, and the AI Sidekick
  (auto-creation intents). See [Command reference](#command-reference).
- A JSON-first CLI suitable for scripting or driving from an agent (every command prints JSON).
- 1Password-friendly: credentials may be `op://` references resolved at runtime.
- Honest about uncertainty: a handful of write bodies are reverse-engineered and accept a
  `--json` / `**extra` pass-through so they keep working as the API is confirmed live.

## Install

```bash
# Until it is published to PyPI, install from git:
pip install "git+https://github.com/joshuaswarren/pyskylight"
# (PyPI, once published: pip install pyskylight)
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

## Command reference

Run `skylight --help`, or `skylight <command> --help` for flags. Every command takes
`--frame` (or uses `SKYLIGHT_FRAME_ID`) where a household is required.

| Area | Commands |
|---|---|
| **Auth / identity** | `login`, `logout`, `whoami` |
| **Frames** | `frames`, `frame`, `frame-rename`, `frame-settings`, `frame-hide`, `frame-activation-code` |
| **Calendar events** | `events`, `events-search`, `countdowns`, `event-invitees`, `event-add`, `event-update`, `event-delete`, `event-notifications`, `event-notifications-update`, `reminder-notification`, `reminder-notification-update` |
| **Connected calendars** | `calendars`, `calendar-account`, `calendar-account-update`, `calendar-link`, `webcals`, `webcal-add`, `source-calendars`, `source-calendar`, `source-calendar-update`, `source-calendar-delete`, `source-calendar-default`, `source-calendar-categorize`, `category-categorize` |
| **Meals — recipes** | `recipes`, `recipe`, `create-recipe`, `update-recipe`, `delete-recipe`, `grocery-add`, `meal-categories`, `update-meal-category` |
| **Meals — plan (sittings)** | `plan`, `plan-show`, `plan-add`, `plan-update`, `plan-remove`, `plan-instances`, `plan-instance-update` |
| **Chores** | `chores`, `chore-add`, `chore-add-multiple`, `chore-update`, `chore-complete`, `chore-delete` |
| **Lists & items** | `lists`, `list-show`, `list-items`, `list-create`, `list-update`, `list-delete`, `list-add`, `list-item-update`, `list-item-complete`, `list-item-delete`, `list-items-delete`, `list-item-move`, `list-items-section` |
| **Categories / profiles** | `categories`, `category`, `category-add`, `category-find-or-create`, `category-update`, `category-delete` |
| **Rewards** | `rewards`, `reward`, `reward-add`, `reward-update`, `reward-delete`, `reward-redeem`, `reward-unredeem`, `reward-points`, `reward-points-set` |
| **Photos / messages** | `messages`, `message`, `message-delete`, `messages-delete`, `messages-copy`, `message-caption`, `message-likes`, `message-like`, `message-unlike`, `message-comments`, `message-comment-add`, `message-comment-delete`, `photo-upload`, `upload-credentials` |
| **Albums** | `albums`, `album-add`, `album-update`, `album-delete`, `album-messages`, `album-message-ids`, `album-add-photos`, `album-remove-photos` |
| **Devices & alarms (Buddy)** | `devices`, `device`, `device-update`, `device-delete`, `device-activation-code`, `device-reset`, `alarms`, `alarm-add`, `alarm-update`, `alarm-delete` |
| **Household** | `members`, `member-invite`, `member-approve`, `member-remove`, `member-update`, `household-config`, `household-config-update`, `plus-status` |
| **Routines / task-box** | `routines`, `routine-add`, `routine-update`, `routine-delete`, `routines-reorder`, `task-box`, `task-box-add`, `task-box-update`, `task-box-delete` |
| **AI Sidekick** | `ai-intents`, `ai-intent`, `ai-intent-create`, `ai-intent-approve`, `ai-intent-retry`, `ai-intent-undo`, `ai-intent-items` |
| **Reference / misc** | `avatars`, `colors`, `activities`, `month-in-review`, `month-in-reviews`, `weather`, `geolocation`, `share-link` |

> Request shapes were verified against the live web client + live API (2026-06): most
> updates take typed flags. **Alarms** apply only to Buddy devices and their body is set
> by the app form, so `alarm-add`/`alarm-update` accept a `--json '{...}'` pass-through.
> Source calendars have no manual create endpoint — add one by linking an account with
> `calendar-link`. Account-level and billing operations (registration/deletion,
> subscription purchase) are intentionally **not** exposed.

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

Login uses the app's **OAuth2 Authorization-Code + PKCE** flow (`/oauth/authorize` →
`/auth/session` → `/oauth/token`) and stores the resulting `access_token` /
`refresh_token`; subsequent requests send `Authorization: Bearer <access_token>`. The
client refreshes (or re-logs-in) automatically when the token expires.

> The older `POST /api/sessions` email/password endpoint is version-gated and
> effectively retired (it returns "This version of Skylight is no longer supported"),
> which is why this client uses the OAuth flow. Verified against the live API
> (2026-06).

> **Skylight Plus:** some Meals features may require Skylight Plus. Where an endpoint
> is forbidden (HTTP 403) it surfaces as `SkylightPlusRequiredError`. (In practice the
> Meals/Recipes/Sittings endpoints work on a "basic" account.)

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
