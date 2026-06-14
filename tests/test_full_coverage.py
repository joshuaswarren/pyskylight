"""Smoke coverage for the full client surface (Tiers 0r–5).

Each new client method is exercised against a catch-all respx route so the
request-building code runs. Write bodies follow the reverse-engineered surface;
these tests assert the methods issue a request and parse the response without
error — they do not assert the remote contract (which is verified live).
"""

from __future__ import annotations

import respx
from httpx import Response

from pyskylight import Credentials, SkylightClient
from pyskylight.constants import API_PREFIX, DEFAULT_BASE_URL

BASE = DEFAULT_BASE_URL
API = API_PREFIX


def _client() -> SkylightClient:
    return SkylightClient(Credentials("123", "tok"))


@respx.mock
def test_full_client_surface_smoke() -> None:
    respx.route(url__regex=r".*").mock(
        return_value=Response(200, json={"data": {"id": "1", "attributes": {}}})
    )
    c = _client()
    calls = [
        # Tier 0 reads
        lambda: c.get_sitting("7", "5"),
        lambda: c.get_sitting("7", "5", include="meal_recipe"),
        lambda: c.get_list("7", "1"),
        lambda: c.list_list_items("7", "1"),
        lambda: c.get_category("7", "2"),
        lambda: c.update_meal_category("7", "2", label="Brunch"),
        # Tier 1 chores
        lambda: c.create_chore(
            "7",
            "Dishes",
            start="2026-06-20",
            start_time="18:00",
            reward_points=5,
            category_id="2",
            recurring=True,
            recurrence_set=["RRULE:FREQ=DAILY"],
            recurring_until="2026-12-31",
            up_for_grabs=True,
            emoji_icon="*",
            status="pending",
        ),
        lambda: c.create_chores("7", [{"summary": "x"}]),
        lambda: c.update_chore("7", "9", summary="Trash", status="complete"),
        lambda: c.complete_chore("7", "9", instance_date="2026-06-20"),
        lambda: c.delete_chore("7", "9", apply_to="all"),
        lambda: c.delete_chore("7", "9"),
        # Tier 1 lists
        lambda: c.create_list(
            "7", "Groceries", color="#fff", kind="shopping", hide_from_frame=False
        ),
        lambda: c.update_list("7", "1", label="Food"),
        lambda: c.delete_list("7", "1"),
        lambda: c.update_list_item("7", "1", "3", label="Milk", status="completed", position=2),
        lambda: c.complete_list_item("7", "1", "3"),
        lambda: c.complete_list_item("7", "1", "3", completed=False),
        lambda: c.delete_list_item("7", "1", "3"),
        lambda: c.delete_list_items("7", "1", ["3", "4"]),
        lambda: c.move_list_item("7", "1", "3", after_item_id="4"),
        lambda: c.set_list_items_section("7", "1", ["3", "4"], "Dairy"),
        # Tier 1 categories
        lambda: c.create_category("7", "Mom", "#5DB671"),
        lambda: c.find_or_create_category("7", "Dad", "#123456"),
        lambda: c.update_category("7", "2", label="Mum"),
        lambda: c.delete_category("7", "2", reassign_to_id="3"),
        lambda: c.delete_category("7", "2"),
        # Tier 1 sitting instances
        lambda: c.list_sitting_instances(
            "7", "5", date_min="2026-06-01", date_max="2026-06-30", include="meal_recipe"
        ),
        lambda: c.update_sitting_instance(
            "7", "5", "2026-06-20", meal_recipe_id="9", meal_category_id="3"
        ),
        # Tier 2 calendars
        lambda: c.list_calendars("7"),
        lambda: c.get_calendar_account("7", "11"),
        lambda: c.update_calendar_account("7", "11", ["a", "b"]),
        lambda: c.calendar_authorization_url(
            "7",
            redirect_url="x",
            failure_redirect_url="y",
            two_way_sync=True,
            provider="google",
            login_hint="a@b.com",
        ),
        lambda: c.list_webcal_accounts("7"),
        lambda: c.subscribe_webcal("7", "webcal://x"),
        lambda: c.list_source_calendars("7"),
        lambda: c.get_source_calendar("7", "21"),
        lambda: c.create_source_calendar("7", name="x"),
        lambda: c.update_source_calendar("7", "21", name="y"),
        lambda: c.delete_source_calendar("7", "21"),
        lambda: c.set_default_source_calendar("7", "21"),
        lambda: c.search_calendar_events("7", "soccer", timezone="UTC"),
        lambda: c.list_countdowns("7"),
        lambda: c.recent_invited_emails("7"),
        lambda: c.get_event_notification_settings("7"),
        lambda: c.update_event_notification_settings("7", enabled=True),
        lambda: c.get_reminder_notification(),
        lambda: c.update_reminder_notification(6),
        lambda: c.set_source_calendar_categorizations("7", "21", [{"a": 1}]),
        lambda: c.set_category_source_calendar_categorizations("7", "2", [{"a": 1}]),
        lambda: c.list_task_box_items("7"),
        lambda: c.create_task_box_item("7", "Call plumber"),
        lambda: c.update_task_box_item("7", "31", title="x"),
        lambda: c.delete_task_box_item("7", "31"),
        lambda: c.list_routines("7"),
        lambda: c.create_routine("7", "Morning", "2", [{"x": 1}]),
        lambda: c.update_routine("7", "41", title="Eve"),
        lambda: c.delete_routine("7", "41"),
        lambda: c.reorder_routines("7", ["41", "42"]),
        # Tier 3 rewards
        lambda: c.list_rewards("7"),
        lambda: c.get_reward("7", "51"),
        lambda: c.create_reward(
            "7",
            "Ice cream",
            10,
            category_ids=["2"],
            emoji_icon="i",
            description="treat",
            respawn_on_redemption=True,
        ),
        lambda: c.update_reward("7", "51", name="Gelato"),
        lambda: c.delete_reward("7", "51"),
        lambda: c.redeem_reward("7", "51"),
        lambda: c.unredeem_reward("7", "51"),
        lambda: c.get_reward_points("7"),
        lambda: c.set_reward_points("7", ["2"], 100),
        # Tier 3 messages
        lambda: c.list_messages("7", page="1"),
        lambda: c.get_message("7", "61"),
        lambda: c.delete_message("7", "61"),
        lambda: c.delete_messages("7", ["61", "62"]),
        lambda: c.copy_messages_to_frames("7", ["61"], ["8"]),
        lambda: c.set_message_caption("7", "61", "hi"),
        lambda: c.list_message_likes("7", "61"),
        lambda: c.like_message("7", "61"),
        lambda: c.unlike_message("7", "61"),
        lambda: c.list_message_comments("7", "61"),
        lambda: c.comment_message("7", "61", "nice"),
        lambda: c.delete_message_comment("7", "61", "71"),
        # Tier 3 albums
        lambda: c.list_albums("7"),
        lambda: c.create_album("7", "Vacation"),
        lambda: c.update_album("7", "81", "Summer"),
        lambda: c.delete_album("7", "81"),
        lambda: c.list_album_messages("7", "81"),
        lambda: c.list_album_message_ids("7", "81"),
        lambda: c.add_to_albums("7", ["81"], ["61"]),
        lambda: c.remove_from_albums("7", ["81"], ["61"]),
        # Tier 3 month-in-review + globals
        lambda: c.month_in_review("7"),
        lambda: c.list_month_in_reviews("7"),
        lambda: c.list_avatars(),
        lambda: c.list_colors(),
        lambda: c.list_activities(),
        lambda: c.cloud_upload_credentials(),
        lambda: c.request_upload_url(
            ext="jpg", frame_ids=["7"], caption="x", trim_start=0.0, trim_end=1.0
        ),
        # Tier 4 devices & alarms
        lambda: c.list_devices("7"),
        lambda: c.get_device("7", "91"),
        lambda: c.update_device("7", "91", name="Kitchen"),
        lambda: c.delete_device("7", "91"),
        lambda: c.device_activation_code("7", "91"),
        lambda: c.reset_device("7", "91"),
        lambda: c.list_alarms("7", "91"),
        lambda: c.create_alarm("7", "91", time="07:00"),
        lambda: c.update_alarm("7", "91", "a1", time="08:00"),
        lambda: c.delete_alarm("7", "91", "a1"),
        # Tier 4 members & config
        lambda: c.list_frame_users("7"),
        lambda: c.invite_frame_user("7", "a@b.com"),
        lambda: c.approve_frame_user("7", "u1"),
        lambda: c.remove_frame_user("7", "u1"),
        lambda: c.update_family_member("7", "m1", name="x"),
        lambda: c.get_household_config("7"),
        lambda: c.update_household_config("7", quiet_hours=True),
        # Tier 4 env / misc / frame
        lambda: c.get_weather(lat="30", lon="-97"),
        lambda: c.get_geolocation(),
        lambda: c.generate_one_link(campaign="x"),
        lambda: c.list_plus_subscriptions("7"),
        lambda: c.frame_rename("7", "Home"),
        lambda: c.update_frame_settings("7", open_to_public=False),
        lambda: c.update_frame_timezone("7", "America/Chicago"),
        lambda: c.hide_frame("7"),
        lambda: c.frame_activation_code("7"),
        # Tier 5 AI intents
        lambda: c.list_auto_creation_intents("7"),
        lambda: c.get_auto_creation_intent("7", "i1"),
        lambda: c.create_auto_creation_intent(
            "7", text="a week of easy dinners", engine="default", draft_first=True, list_id="1"
        ),
        lambda: c.approve_auto_creation_intent("7", "i1"),
        lambda: c.retry_auto_creation_intent("7", "i1"),
        lambda: c.undo_auto_creation_intent("7", "i1"),
        lambda: c.auto_creation_intent_items("7", "i1"),
    ]
    for fn in calls:
        fn()


@respx.mock
def test_upload_photo_two_step(tmp_path) -> None:
    img = tmp_path / "p.jpg"
    img.write_bytes(b"bytes")
    respx.post(f"{BASE}{API}/upload_url").mock(
        return_value=Response(
            200, json={"data": {"attributes": {"upload_url": "https://up.example/abc"}}}
        )
    )
    put = respx.put("https://up.example/abc").mock(return_value=Response(200))
    _client().upload_photo("7", str(img), caption="hi")
    assert put.called


@respx.mock
def test_upload_photo_without_presigned_url_returns_payload(tmp_path) -> None:
    img = tmp_path / "p.jpg"
    img.write_bytes(b"bytes")
    respx.post(f"{BASE}{API}/upload_url").mock(
        return_value=Response(200, json={"data": {"attributes": {}}})
    )
    out = _client().upload_photo("7", str(img))
    assert out["data"]["attributes"] == {}
