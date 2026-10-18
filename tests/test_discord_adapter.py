"""Discord command boundary tests without a live Discord connection."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

import bot_application
from bot_application import CoinCandidate, CoinCreationError, CoinInfo, CoinInfoError, CoinUpdateError
from discord_adapter import DiscordAdapter
from discord_bot import _admin_ids
from wen import WenReply


@pytest.fixture
def interaction(discord_context):
    return SimpleNamespace(
        user=SimpleNamespace(id=int(discord_context.user_id), display_name=discord_context.display_name),
        channel_id=123,
        response=SimpleNamespace(send_message=AsyncMock(), defer=AsyncMock(), edit_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


@pytest.fixture
def recipient():
    return SimpleNamespace(send=AsyncMock())


@pytest.fixture
def adapter(application, recipient, run_async):
    client = DiscordAdapter(application, {7}, 123)
    client.get_user = Mock(return_value=None)
    client.fetch_user = AsyncMock(return_value=recipient)

    yield client

    run_async(client.close())


@pytest.fixture
def triggered_alert(application, discord_context, market_lookup, market_quote):
    application.price_notify(discord_context, "TST", 12)
    market_lookup.return_value = market_quote(13)
    return application.price_alerts.due_notifications()[0]


@pytest.fixture
def new_coin():
    return CoinCandidate("NEW", "New Coin", "43", "https://example.com", None, None)


@pytest.fixture
def pending_update(adapter, interaction, run_async):
    interaction.user.id = 7
    command = adapter.tree.get_command("update_crypto")
    run_async(command.callback(interaction, "tst", "website", "https://new.example.com"))
    return interaction.followup.send.call_args.kwargs["view"]


def test_info_shows_readable_coin_card(adapter, application, interaction, run_async):
    application.info = Mock(
        return_value=CoinInfo(
            "TST",
            "Test Coin",
            [("Network", "ETH ERC-20"), ("Website", "https://example.com"), ("Contract address", "0xabc")],
            [("CoinMarketCap", "https://coinmarketcap.com/currencies/test-coin/")],
        )
    )
    command = adapter.tree.get_command("info")

    run_async(command.callback(interaction, "tst"))

    interaction.response.defer.assert_awaited_once_with(thinking=True)
    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert embed.title == "Test Coin (TST)"
    assert [(field.name, field.value) for field in embed.fields] == [
        ("Network", "ETH ERC-20"),
        ("Website", "[Visit website](https://example.com)"),
        ("Contract address", "`0xabc`"),
        ("Links", "[CoinMarketCap](https://coinmarketcap.com/currencies/test-coin/)"),
    ]
    assert embed.fields[2].inline is False


def test_info_attaches_metadata_that_exceeds_embed_limits(adapter, application, interaction, run_async):
    info = CoinInfo("TST", "Test Coin", [("Description", "x" * 2100)], [])
    application.info = Mock(return_value=info)
    command = adapter.tree.get_command("info")

    run_async(command.callback(interaction, "TST"))

    attachment = interaction.followup.send.call_args.kwargs["file"]
    assert attachment.filename == "info.txt"
    assert attachment.fp.read().decode("utf-8") == info.as_text()


def test_info_explains_unknown_coin(adapter, application, interaction, run_async):
    application.info = Mock(side_effect=CoinInfoError("Unknown coin: MISSING"))
    command = adapter.tree.get_command("info")

    run_async(command.callback(interaction, "missing"))

    interaction.followup.send.assert_awaited_once_with("Unknown coin: MISSING", ephemeral=False)


def test_wen_offers_choices_and_uses_shared_reply(adapter, application, interaction, discord_context, run_async):
    application.wen = Mock(return_value=WenReply("HODL"))
    command = adapter.tree.get_command("wen")

    run_async(command.callback(interaction, "moon"))

    assert [choice.value for choice in command.parameters[0].choices] == ["moon", "lambo", "aston"]
    application.wen.assert_called_once_with(discord_context, "moon")
    interaction.response.send_message.assert_awaited_once_with("HODL")
    interaction.followup.send.assert_not_awaited()


def test_wen_sends_optional_moon_audio(adapter, application, interaction, moon_audio, run_async):
    application.wen = Mock(return_value=WenReply("HODL", moon_audio))
    command = adapter.tree.get_command("wen")

    run_async(command.callback(interaction, "moon"))

    interaction.response.send_message.assert_awaited_once_with("HODL")
    attachment = interaction.followup.send.call_args.kwargs["file"]
    assert attachment.filename == "wen_moon.ogg"
    assert attachment.fp.closed


def test_wen_keeps_text_reply_when_audio_upload_fails(adapter, application, interaction, moon_audio, run_async):
    application.wen = Mock(return_value=WenReply("HODL", moon_audio))
    interaction.followup.send.side_effect = discord.HTTPException(
        SimpleNamespace(status=413, reason="Payload Too Large"), "File too large"
    )
    command = adapter.tree.get_command("wen")

    run_async(command.callback(interaction, "moon"))

    interaction.response.send_message.assert_awaited_once_with("HODL")
    attachment = interaction.followup.send.call_args.kwargs["file"]
    assert attachment.fp.closed


def test_ethgas_shows_gas_tiers_in_a_card(adapter, application, interaction, discord_context, gas_prices, run_async):
    application.ethgas = Mock(return_value=gas_prices)
    command = adapter.tree.get_command("ethgas")

    run_async(command.callback(interaction))

    interaction.response.defer.assert_awaited_once_with(thinking=True)
    application.ethgas.assert_called_once_with(discord_context)
    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert embed.title == "Ethereum gas"
    assert embed.description == "Estimated Uniswap swap cost • 152,000 gas"
    assert [(field.name, field.value) for field in embed.fields] == [
        ("Safe", "1.25 gwei ($0.3800)"),
        ("Proposed", "2 gwei ($0.6080)"),
        ("Fast", "3 gwei ($0.9120)"),
    ]


def test_ethgas_explains_missing_configuration(adapter, interaction, run_async):
    command = adapter.tree.get_command("ethgas")

    run_async(command.callback(interaction))

    interaction.followup.send.assert_awaited_once_with(
        "Ethereum gas prices are not configured. Set ETHERSCAN_API_KEY to use /ethgas."
    )


def test_check_notifications_replies_privately(adapter, application, interaction, run_async):
    response = "TST at $12.0\n"
    application.check_notifications = Mock(return_value=response)
    command = adapter.tree.get_command("check_notifications")

    run_async(command.callback(interaction))

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    interaction.followup.send.assert_awaited_once_with(response, ephemeral=True)


def test_check_notifications_attaches_long_lists_privately(adapter, application, interaction, run_async):
    long_response = "TST at $12.0\n" * 200
    application.check_notifications = Mock(return_value=long_response)
    command = adapter.tree.get_command("check_notifications")

    run_async(command.callback(interaction))

    reply = interaction.followup.send.call_args
    attachment = reply.kwargs["file"]
    assert reply.kwargs["ephemeral"] is True
    assert attachment.filename == "notifications.txt"
    assert attachment.fp.read().decode("utf-8") == long_response


def test_delete_notification_replies_privately(adapter, application, interaction, discord_context, run_async):
    response = "Notification for TST deleted"
    application.delete_notification = Mock(return_value=response)
    command = adapter.tree.get_command("delete_notification")

    run_async(command.callback(interaction, "tst"))

    application.delete_notification.assert_called_once_with(discord_context, "tst")
    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    interaction.followup.send.assert_awaited_once_with(response, ephemeral=True)


def test_checker_skips_alert_canceled_during_user_lookup(
    adapter, application, recipient, discord_context, triggered_alert, run_async
):
    async def cancel_during_user_lookup(_user_id):
        application.delete_notification(discord_context, triggered_alert.coin)
        return recipient

    adapter.fetch_user.side_effect = cancel_during_user_lookup

    run_async(adapter.check_price_notifications())

    recipient.send.assert_not_awaited()
    assert application.check_notifications(discord_context) == "No notifications set"


def test_price_notify_registers_user_and_confirms_privately(adapter, application, interaction, run_async):
    command = adapter.tree.get_command("price_notify")

    run_async(command.callback(interaction, "tst", 12.0))

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    confirmation = interaction.followup.send.call_args
    assert "Created notification for TST at $12.0" in confirmation.args[0]
    assert confirmation.kwargs["ephemeral"] is True
    assert application.price_alerts.has_user(str(interaction.user.id))


def test_price_notify_explains_invalid_target(adapter, interaction, run_async):
    command = adapter.tree.get_command("price_notify")

    run_async(command.callback(interaction, "TST", -1))

    confirmation = interaction.followup.send.call_args
    assert "positive, finite" in confirmation.args[0]
    assert confirmation.kwargs["ephemeral"] is True


def test_blocked_dm_is_retained_and_retried(adapter, application, recipient, triggered_alert, run_async):
    recipient.send.side_effect = discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "Cannot send messages to this user"
    )

    run_async(adapter.check_price_notifications())

    assert application.price_alerts.due_notifications() == [triggered_alert]
    recipient.send.side_effect = None
    recipient.send.reset_mock()

    run_async(adapter.check_price_notifications())
    run_async(adapter.check_price_notifications())

    recipient.send.assert_awaited_once_with(triggered_alert.message())
    assert application.price_alerts.due_notifications() == []
    adapter.fetch_user.assert_awaited_with(triggered_alert.user_id)


def test_alert_scheduler_waits_for_ready_and_stops_on_close(adapter, application, run_async):
    ready = asyncio.Event()
    adapter.wait_until_ready = AsyncMock(side_effect=ready.wait)
    adapter.tree.sync = AsyncMock()
    application.price_alerts.due_notifications = Mock(return_value=[])

    run_async(adapter.setup_hook())
    run_async(asyncio.sleep(0))

    task = adapter.check_price_notifications.get_task()
    assert adapter.check_price_notifications.is_running()
    assert adapter.check_price_notifications.minutes == 15
    adapter.wait_until_ready.assert_awaited_once()
    application.price_alerts.due_notifications.assert_not_called()

    run_async(adapter.close())

    assert task.cancelled()
    assert not adapter.check_price_notifications.is_running()


@pytest.mark.parametrize(
    ("current_price", "change", "expected"),
    [
        (48992.267342, -6.234, "TST Price: $48992.2673420000\n⬇️ -6.23% (24H)"),
        (0.0001234567, 2.346, "TST Price: $0.0001234567\n⬆️ 2.35% (24H)"),
    ],
    ids=["falling-price", "small-rising-price"],
)
def test_price_defers_lookup_and_formats_quote(
    adapter,
    application,
    interaction,
    discord_context,
    market_lookup,
    market_quote,
    run_async,
    current_price,
    change,
    expected,
):
    def lookup(coin_id, key):
        interaction.response.defer.assert_awaited_once_with(thinking=True)
        interaction.followup.send.assert_not_awaited()
        return market_quote(current_price, change)

    market_lookup.side_effect = lookup
    application.price = Mock(wraps=application.price)
    command = adapter.tree.get_command("price")

    run_async(command.callback(interaction, " tst "))

    application.price.assert_called_once_with(discord_context, " tst ")
    market_lookup.assert_called_once_with("42", "cmc-key")
    interaction.followup.send.assert_awaited_once_with(expected, ephemeral=False)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"status": {"error_code": 1008, "error_message": "Rate limit exceeded"}},
        {"data": {"42": {"quote": {"USD": {"price": None}}}}},
    ],
    ids=["unavailable", "rate-limit", "invalid-quote"],
)
def test_price_handles_unavailable_quotes(application, discord_context, market_lookup, payload):
    market_lookup.return_value = payload

    response = application.price(discord_context, "TST")

    assert response == "Could not get the latest price. Try again later."


def test_price_rejects_unknown_coin_without_lookup(application, discord_context, market_lookup):
    response = application.price(discord_context, "missing")

    assert response == "Unknown coin: MISSING\n\nKnown coins:TST"
    market_lookup.assert_not_called()


def test_coin_creation_is_shared_and_persisted(application, discord_context, new_coin, monkeypatch):
    application.cryptos.clear()
    monkeypatch.setattr(bot_application, "cmc_id_map", Mock(return_value={"data": [{"id": 43}]}))
    monkeypatch.setattr(
        bot_application,
        "get_coin_info",
        Mock(
            return_value={
                "data": {
                    "43": {
                        "symbol": new_coin.symbol,
                        "name": new_coin.name,
                        "slug": "new-coin",
                        "urls": {"website": [new_coin.website]},
                        "platform": None,
                    }
                }
            }
        ),
    )

    candidate = application.prepare_new_coin("new")
    application.add_coin(candidate)

    assert application.coins(discord_context) == "Known coins:\nNEW"
    saved_coins = json.loads(application.crypto_path.read_text(encoding="utf-8"))
    assert saved_coins["NEW"]["cmc_id"] == "43"
    assert saved_coins["NEW"]["cmc_slug"] == "new-coin"
    with pytest.raises(CoinCreationError, match="already known"):
        application.add_coin(candidate)


@pytest.mark.parametrize(
    ("command_name", "arguments"),
    [("new_crypto", ("NEW",)), ("update_crypto", ("TST", "website", "https://example.com"))],
    ids=["add-coin", "update-coin"],
)
def test_coin_management_requires_admin(adapter, application, interaction, run_async, command_name, arguments):
    command = adapter.tree.get_command(command_name)

    run_async(command.callback(interaction, *arguments))

    reply = interaction.response.send_message.call_args
    assert "Only admins" in reply.args[0]
    assert reply.kwargs["ephemeral"] is True
    assert "NEW" not in application.cryptos
    assert not application.crypto_path.exists()


def test_new_crypto_confirmation_saves_coin(adapter, application, interaction, new_coin, run_async):
    interaction.user.id = 7
    application.prepare_new_coin = Mock(return_value=new_coin)
    command = adapter.tree.get_command("new_crypto")
    run_async(command.callback(interaction, "NEW"))
    confirmation_view = interaction.followup.send.call_args.kwargs["view"]

    run_async(confirmation_view.children[0].callback(interaction))

    reply = interaction.response.edit_message.call_args
    assert "has been added" in reply.kwargs["content"]
    saved_coins = json.loads(application.crypto_path.read_text(encoding="utf-8"))
    assert "NEW" in saved_coins


def test_update_crypto_previews_change_privately(application, interaction, pending_update):
    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    reply = interaction.followup.send.call_args
    assert reply.args[0] == (
        "Update TST: website\n\nCurrent: (not set)\nNew: https://new.example.com\n\nSave this change?"
    )
    assert reply.kwargs["ephemeral"] is True
    assert [button.label for button in pending_update.children] == ["Save changes", "Cancel"]
    assert application.cryptos == {"TST": {"cmc_id": "42"}}
    assert not application.crypto_path.exists()


def test_update_crypto_confirmation_saves_coin(application, interaction, pending_update, run_async):
    run_async(pending_update.children[0].callback(interaction))

    saved = json.loads(application.crypto_path.read_text(encoding="utf-8"))
    assert saved["TST"]["INFO"]["website"] == "https://new.example.com"
    interaction.edit_original_response.assert_awaited_once_with(
        content="Success. TST's website has been updated.", attachments=[], view=None
    )
    assert pending_update.is_finished()


def test_update_crypto_cancel_keeps_catalog_unchanged(application, interaction, pending_update, run_async):
    run_async(pending_update.children[1].callback(interaction))

    assert application.cryptos == {"TST": {"cmc_id": "42"}}
    assert not application.crypto_path.exists()
    interaction.response.edit_message.assert_awaited_once_with(content="Aborting command.", attachments=[], view=None)
    assert pending_update.is_finished()


def test_update_crypto_buttons_reject_other_users(interaction, pending_update, run_async):
    interaction.user.id = 8

    allowed = run_async(pending_update.interaction_check(interaction))

    assert allowed is False
    interaction.response.send_message.assert_awaited_once_with(
        "Only the command creator can confirm this change.", ephemeral=True
    )


def test_update_crypto_explains_unknown_coin(adapter, interaction, run_async):
    interaction.user.id = 7
    command = adapter.tree.get_command("update_crypto")

    run_async(command.callback(interaction, "missing", "website", "https://example.com"))

    interaction.followup.send.assert_awaited_once_with("Cannot update coin: unknown coin MISSING", ephemeral=True)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (CoinUpdateError("This field changed after your preview."), "This field changed after your preview."),
        (OSError("Disk unavailable"), "Could not save the coin information. Try again later."),
    ],
    ids=["stale-preview", "save-failure"],
)
def test_update_crypto_explains_save_failure(application, interaction, pending_update, run_async, error, expected):
    application.update_coin = Mock(side_effect=error)

    run_async(pending_update.children[0].callback(interaction))

    interaction.edit_original_response.assert_awaited_once_with(content=expected, attachments=[], view=None)
    assert not application.crypto_path.exists()


def test_update_crypto_attaches_long_previews(adapter, application, interaction, run_async):
    interaction.user.id = 7
    old_value = "x" * 2100
    application.cryptos["TST"]["INFO"] = {"custom_note": old_value}
    command = adapter.tree.get_command("update_crypto")

    run_async(command.callback(interaction, "TST", "custom_note", "Shorter note"))

    reply = interaction.followup.send.call_args
    attachment = reply.kwargs["file"]
    assert attachment.filename == "update_crypto.txt"
    assert old_value in attachment.fp.read().decode("utf-8")
    assert reply.kwargs["ephemeral"] is True
    assert reply.kwargs["view"] is not None
    assert application.cryptos["TST"]["INFO"]["custom_note"] == old_value


def test_discord_admin_ids_must_be_configured():
    assert _admin_ids("[7, 8]") == {7, 8}

    with pytest.raises(ValueError, match="nonempty"):
        _admin_ids("[]")
