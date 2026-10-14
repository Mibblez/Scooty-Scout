"""Price alert persistence and threshold checks without network requests."""

import sqlite3
from contextlib import closing

import pytest

from backend_config import Backend
from command_context import CommandContext
from price_alerts import PriceAlerts, PriceAlertError


def test_check_notifications_is_empty_without_market_lookup(application, discord_context, market_lookup):
    response = application.check_notifications(discord_context)

    assert response == "No notifications set"
    market_lookup.assert_not_called()


def test_check_notifications_lists_only_callers_alerts(application, discord_context, market_lookup):
    other_user = CommandContext(Backend.DISCORD, "9", "123", "Grace")
    application.price_notify(discord_context, "TST", 12)
    application.price_notify(other_user, "TST", 8)
    market_lookup.reset_mock()

    response = application.check_notifications(discord_context)

    assert response == "TST at $12.0\n"
    assert application.check_notifications(other_user) == "TST at $8.0\n"
    market_lookup.assert_not_called()


def test_delete_notification_removes_only_matching_user_and_coin(application, discord_context, market_lookup):
    other_user = CommandContext(Backend.DISCORD, "9", "123", "Grace")
    application.cryptos["ALT"] = {"cmc_id": "42"}
    application.price_notify(discord_context, "TST", 12)
    application.price_notify(discord_context, "ALT", 9)
    application.price_notify(other_user, "TST", 8)
    market_lookup.reset_mock()

    response = application.delete_notification(discord_context, " tst ")

    assert response == "Notification for TST deleted"
    assert application.check_notifications(discord_context) == "ALT at $9.0\n"
    assert application.check_notifications(other_user) == "TST at $8.0\n"
    market_lookup.assert_not_called()


def test_delete_notification_explains_missing_alert(application, discord_context, market_lookup):
    response = application.delete_notification(discord_context, "TST")

    assert response == "You don't have a notification set for TST"
    market_lookup.assert_not_called()


def test_delete_unknown_coin_preserves_saved_alert(application, discord_context, market_lookup):
    application.price_notify(discord_context, "TST", 12)
    market_lookup.reset_mock()

    response = application.delete_notification(discord_context, "missing")

    assert response == "You don't have a notification set for MISSING"
    assert application.check_notifications(discord_context) == "TST at $12.0\n"
    market_lookup.assert_not_called()


def test_delete_notification_works_after_coin_leaves_catalog(application, discord_context, market_lookup):
    application.price_notify(discord_context, "TST", 12)
    del application.cryptos["TST"]
    market_lookup.reset_mock()

    response = application.delete_notification(discord_context, "tst")

    assert response == "Notification for TST deleted"
    assert application.check_notifications(discord_context) == "No notifications set"
    market_lookup.assert_not_called()


@pytest.fixture
def legacy_telegram_alerts(tmp_path, application):
    path = tmp_path / "notifications.db"
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE users(user_id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute(
            "CREATE TABLE price_notifications("
            "notification_id INTEGER PRIMARY KEY AUTOINCREMENT, coin TEXT, "
            "user_id INTEGER, notify_at FLOAT, direction CHAR)"
        )
        connection.execute("INSERT INTO users VALUES (8, 'Ada')")
        connection.execute("INSERT INTO price_notifications VALUES (1, 'TST', 8, 8, '-')")
    return PriceAlerts(application.cryptos, application.cmc_api_key, path)


def test_existing_telegram_alert_survives_initialization(legacy_telegram_alerts, market_lookup, market_quote):
    market_lookup.return_value = market_quote(7)

    (pending_alert,) = legacy_telegram_alerts.due_notifications()

    assert legacy_telegram_alerts.has_user("8")
    assert pending_alert.target == 8
    assert pending_alert.direction == "-"


def test_discord_users_and_alerts_are_separate_from_telegram(
    alerts, legacy_telegram_alerts, discord_context, market_lookup, market_quote
):
    assert not alerts.has_user(discord_context.user_id)
    alerts.set_notification(discord_context, "TST", 12)
    market_lookup.return_value = market_quote(7)

    assert alerts.due_notifications() == []
    assert len(legacy_telegram_alerts.due_notifications()) == 1

    market_lookup.return_value = market_quote(13)

    assert len(alerts.due_notifications()) == 1
    assert legacy_telegram_alerts.due_notifications() == []


def test_discord_alert_survives_reopening_database(alerts, discord_context, market_lookup, market_quote):
    alerts.set_notification(discord_context, "tst", 12)
    market_lookup.return_value = market_quote(13)

    reopened = PriceAlerts(alerts.cryptos, alerts.cmc_api_key, alerts.db_path)

    assert reopened.has_user(discord_context.user_id)
    (pending_alert,) = reopened.due_notifications()
    assert (pending_alert.coin, pending_alert.target) == ("TST", 12)


def test_delivering_old_alert_does_not_delete_its_replacement(alerts, discord_context, market_lookup, market_quote):
    alerts.set_notification(discord_context, "TST", 12)
    market_lookup.return_value = market_quote(13)
    (old_alert,) = alerts.due_notifications()
    market_lookup.return_value = market_quote(10)
    alerts.set_notification(discord_context, "TST", 11)

    alerts.acknowledge(old_alert.notification_id)
    market_lookup.return_value = market_quote(13)

    (replacement,) = alerts.due_notifications()
    assert replacement.target == 11
    assert replacement.notification_id != old_alert.notification_id


@pytest.mark.parametrize(
    ("target_price", "crossed_price", "direction"),
    [(12, 13, "+"), (8, 7, "-")],
    ids=["rising-price", "falling-price"],
)
def test_alert_triggers_only_after_crossing_target(
    alerts, discord_context, market_lookup, market_quote, target_price, crossed_price, direction
):
    alerts.set_notification(discord_context, "TST", target_price)
    market_lookup.return_value = market_quote(target_price)
    assert alerts.due_notifications() == []

    market_lookup.return_value = market_quote(crossed_price)

    (triggered_alert,) = alerts.due_notifications()
    assert triggered_alert.direction == direction


def test_acknowledging_alert_keeps_other_users_alerts(alerts, discord_context, market_lookup, market_quote):
    other_user = CommandContext(Backend.DISCORD, "9", "123", "Grace")
    alerts.set_notification(discord_context, "TST", 12)
    alerts.set_notification(other_user, "TST", 12)
    market_lookup.return_value = market_quote(13)
    first_alert, second_alert = alerts.due_notifications()

    alerts.acknowledge(first_alert.notification_id)

    assert alerts.due_notifications() == [second_alert]
    alerts.acknowledge(second_alert.notification_id)
    market_lookup.reset_mock()
    assert alerts.due_notifications() == []
    market_lookup.assert_not_called()


def test_market_lookup_is_shared_by_users_and_skipped_without_alerts(
    alerts, discord_context, market_lookup, market_quote
):
    assert alerts.due_notifications() == []
    market_lookup.assert_not_called()
    other_user = CommandContext(Backend.DISCORD, "9", "123", "Grace")
    alerts.set_notification(discord_context, "TST", 12)
    alerts.set_notification(other_user, "TST", 12)
    market_lookup.return_value = market_quote(13)
    market_lookup.reset_mock()

    assert len(alerts.due_notifications()) == 2

    market_lookup.assert_called_once_with("42", "cmc-key")


@pytest.mark.parametrize(
    "target_price",
    [0, -1, float("nan"), float("inf"), "not-a-price"],
    ids=["zero", "negative", "nan", "infinity", "text"],
)
def test_invalid_target_keeps_existing_alert(alerts, discord_context, market_lookup, market_quote, target_price):
    alerts.set_notification(discord_context, "TST", 12)
    market_lookup.reset_mock()

    with pytest.raises(PriceAlertError, match="positive, finite"):
        alerts.set_notification(discord_context, "TST", target_price)

    market_lookup.assert_not_called()
    market_lookup.return_value = market_quote(13)
    (existing_alert,) = alerts.due_notifications()
    assert existing_alert.target == 12


def test_unknown_coin_is_rejected_without_market_lookup(alerts, discord_context, market_lookup):
    with pytest.raises(PriceAlertError, match="Unknown coin"):
        alerts.set_notification(discord_context, "missing", 12)

    market_lookup.assert_not_called()


@pytest.mark.parametrize("failure", ["unavailable", "api-error", "invalid-price"])
def test_market_failure_preserves_existing_alert(alerts, discord_context, market_lookup, market_quote, failure):
    alerts.set_notification(discord_context, "TST", 12)
    failed_quotes = {
        "unavailable": None,
        "api-error": {"status": {"error_code": 1008}},
        "invalid-price": market_quote(float("nan")),
    }
    market_lookup.return_value = failed_quotes[failure]

    with pytest.raises(PriceAlertError, match="latest price"):
        alerts.set_notification(discord_context, "TST", 11)
    assert alerts.due_notifications() == []

    market_lookup.return_value = market_quote(13)
    (existing_alert,) = alerts.due_notifications()
    assert existing_alert.target == 12
