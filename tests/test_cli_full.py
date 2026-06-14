"""Smoke coverage for every Tier 0r–5 CLI command.

A fake client whose ``__getattr__`` accepts any method call stands in for the
real client, so each command's argument-parsing and dispatch path runs end to
end and returns exit code 0.
"""

from __future__ import annotations

from typing import Any, List

import pytest
from typer.testing import CliRunner

from pyskylight import cli

runner = CliRunner()


class FakeAll:
    """Accepts any client method call and returns a canned JSON:API payload."""

    def __init__(self) -> None:
        self.calls: list = []

    def __getattr__(self, name: str) -> Any:
        def f(*a: Any, **k: Any) -> Any:
            self.calls.append((name, a, k))
            return {"data": {"id": "1", "attributes": {"summary": "x"}}}

        return f


NEW_COMMANDS: List[List[str]] = [
    # Tier 0 reads
    ["plan-show", "5"],
    ["list-show", "1"],
    ["list-items", "1"],
    ["category", "2"],
    ["update-meal-category", "2", "--json", '{"label":"Brunch"}'],
    # Tier 1 chores
    ["chore-add", "--summary", "Dishes", "--reward-points", "5", "--rrule", "RRULE:FREQ=DAILY"],
    ["chore-add-multiple", "--json", '[{"summary":"x"}]'],
    ["chore-update", "9", "--summary", "Trash", "--status", "complete"],
    ["chore-complete", "9", "--instance-date", "2026-06-20"],
    ["chore-delete", "9", "--apply-to", "all"],
    # Tier 1 lists
    ["list-create", "--label", "Groceries", "--color", "#fff", "--kind", "shopping"],
    ["list-update", "1", "--label", "Food"],
    ["list-delete", "1"],
    ["list-item-update", "1", "3", "--label", "Milk", "--status", "completed"],
    ["list-item-complete", "1", "3"],
    ["list-item-delete", "1", "3"],
    ["list-items-delete", "1", "--id", "3", "--id", "4"],
    ["list-item-move", "1", "3", "--after-item-id", "4"],
    ["list-items-section", "1", "--section", "Dairy", "--id", "3"],
    # Tier 1 categories
    ["category-add", "--label", "Mom", "--color", "#5DB671"],
    ["category-find-or-create", "--label", "Dad", "--color", "#123456"],
    ["category-update", "2", "--label", "Mum"],
    ["category-delete", "2", "--reassign-to-id", "3"],
    # Tier 1 sitting instances
    ["plan-instances", "5", "--from", "2026-06-01", "--to", "2026-06-30"],
    ["plan-instance-update", "5", "--date", "2026-06-20", "--recipe-id", "9"],
    # Tier 2 calendar integration
    ["calendars"],
    ["calendar-account", "11"],
    ["calendar-account-update", "11", "--active-calendar", "a", "--active-calendar", "b"],
    ["calendar-link", "--redirect-url", "x", "--failure-redirect-url", "y", "--provider", "google"],
    ["webcals"],
    ["webcal-add", "--sync-url", "webcal://x"],
    ["source-calendars"],
    ["source-calendar", "21"],
    ["source-calendar-add", "--json", '{"name":"x"}'],
    ["source-calendar-update", "21", "--json", '{"name":"y"}'],
    ["source-calendar-delete", "21"],
    ["source-calendar-default", "21"],
    ["events-search", "--query", "soccer", "--tz", "UTC"],
    ["countdowns"],
    ["event-invitees"],
    ["event-notifications"],
    ["event-notifications-update", "--json", '{"enabled":true}'],
    ["reminder-notification"],
    ["reminder-notification-update", "--json", '{"minutes":10}'],
    ["source-calendar-categorize", "21", "--json", '[{"a":1}]'],
    ["category-categorize", "2", "--json", '[{"a":1}]'],
    ["task-box"],
    ["task-box-add", "--title", "Call plumber"],
    ["task-box-update", "31", "--json", '{"title":"x"}'],
    ["task-box-delete", "31"],
    ["routines"],
    ["routine-add", "--title", "Morning", "--assignee-id", "2", "--json", '[{"x":1}]'],
    ["routine-update", "41", "--title", "Eve"],
    ["routine-delete", "41"],
    ["routines-reorder", "--id", "41", "--id", "42"],
    # Tier 3 rewards
    ["rewards"],
    ["reward", "51"],
    ["reward-add", "--name", "Ice cream", "--point-value", "10", "--category-id", "2"],
    ["reward-update", "51", "--name", "Gelato"],
    ["reward-delete", "51"],
    ["reward-redeem", "51"],
    ["reward-unredeem", "51"],
    ["reward-points"],
    ["reward-points-set", "--points", "100", "--category-id", "2"],
    # Tier 3 messages
    ["messages", "--page", "1"],
    ["message", "61"],
    ["message-delete", "61"],
    ["messages-delete", "--id", "61", "--id", "62"],
    ["messages-copy", "--id", "61", "--to-frame", "8"],
    ["message-caption", "61", "--caption", "hi"],
    ["message-likes", "61"],
    ["message-like", "61"],
    ["message-unlike", "61"],
    ["message-comments", "61"],
    ["message-comment-add", "61", "--body", "nice"],
    ["message-comment-delete", "61", "71"],
    ["photo-upload", "--file", "/tmp/x.jpg", "--caption", "hi"],
    ["upload-credentials"],
    # Tier 3 albums
    ["albums"],
    ["album-add", "--title", "Vacation"],
    ["album-update", "81", "--title", "Summer"],
    ["album-delete", "81"],
    ["album-messages", "81"],
    ["album-message-ids", "81"],
    ["album-add-photos", "--album-id", "81", "--message-id", "61"],
    ["album-remove-photos", "--album-id", "81", "--message-id", "61"],
    # Tier 3 month-in-review + globals
    ["month-in-review"],
    ["month-in-reviews"],
    ["avatars"],
    ["colors"],
    ["activities"],
    # Tier 4 devices & alarms
    ["devices"],
    ["device", "91"],
    ["device-update", "91", "--json", '{"name":"Kitchen"}'],
    ["device-delete", "91"],
    ["device-activation-code", "91"],
    ["device-reset", "91", "--yes"],
    ["alarms", "--device-id", "91"],
    ["alarm-add", "--device-id", "91", "--json", '{"time":"07:00"}'],
    ["alarm-update", "a1", "--device-id", "91", "--json", '{"time":"08:00"}'],
    ["alarm-delete", "a1", "--device-id", "91"],
    # Tier 4 members & config
    ["members"],
    ["member-invite", "--email", "a@b.com"],
    ["member-approve", "u1"],
    ["member-remove", "u1"],
    ["member-update", "m1", "--json", '{"name":"x"}'],
    ["household-config"],
    ["household-config-update", "--json", '{"quiet_hours":true}'],
    # Tier 4 env / misc / frame
    ["weather", "--lat", "30", "--lon", "-97"],
    ["geolocation"],
    ["share-link", "--json", '{"campaign":"x"}'],
    ["plus-status"],
    ["frame-rename", "--name", "Home"],
    ["frame-settings", "--private", "--timezone", "America/Chicago"],
    ["frame-hide"],
    ["frame-activation-code"],
    # Tier 5 AI intents
    ["ai-intents"],
    ["ai-intent", "i1"],
    ["ai-intent-create", "--type", "recipe", "--json", '{"prompt":"tacos"}'],
    ["ai-intent-approve", "i1"],
    ["ai-intent-retry", "i1"],
    ["ai-intent-undo", "i1"],
    ["ai-intent-items", "i1"],
]


@pytest.fixture
def fake_all(monkeypatch):
    fc = FakeAll()
    monkeypatch.setattr(cli, "_build_client", lambda settings: fc)
    monkeypatch.setenv("SKYLIGHT_FRAME_ID", "7")
    return fc


@pytest.mark.parametrize("argv", NEW_COMMANDS, ids=[a[0] for a in NEW_COMMANDS])
def test_new_cli_command(argv, fake_all):
    result = runner.invoke(cli.app, argv)
    assert (
        result.exit_code == 0
    ), f"{argv} -> {result.exit_code}: {result.stdout} {result.exception}"


def test_device_reset_requires_yes(fake_all):
    assert runner.invoke(cli.app, ["device-reset", "91"]).exit_code != 0


def test_frame_settings_requires_something(fake_all):
    assert runner.invoke(cli.app, ["frame-settings"]).exit_code != 0


def test_bad_json_arg_rejected(fake_all):
    assert runner.invoke(cli.app, ["device-update", "91", "--json", "{not json}"]).exit_code != 0
