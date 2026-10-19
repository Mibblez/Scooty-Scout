"""Discord command boundary tests without a live Discord connection."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord
import pytest

import bot_application
from bot_application import CoinCandidate, CoinCreationError, CoinInfo, CoinInfoError, CoinUpdateError
from discord_adapter import DiscordAdapter
from discord_bot import _admin_ids
from group_notifications import GroupNotificationError
from wen import WenReply


@pytest.fixture
def interaction(discord_context):
    return SimpleNamespace(
        user=SimpleNamespace(id=int(discord_context.user_id), display_name=discord_context.display_name),
        channel_id=123,
        guild_id=456,
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
def invoke_command(adapter, interaction, run_async):
    def invoke(name, *arguments):
        command = adapter.tree.get_command(name)
        return run_async(command.callback(interaction, *arguments))

    return invoke


@pytest.fixture
def triggered_alert(alert_application, discord_context, market_lookup, market_quote):
    alert_application.price_notify(discord_context, "TST", 12)
    market_lookup.return_value = market_quote(13)
    return alert_application.price_alerts.due_notifications()[0]


@pytest.fixture
def image_upload():
    return SimpleNamespace(
        filename="upload.PNG", content_type="image/png", size=5, read=AsyncMock(return_value=b"image")
    )


@pytest.fixture
def new_coin():
    return CoinCandidate("NEW", "New Coin", "43", "https://example.com", None, None)


@pytest.fixture
def pending_update(invoke_command, interaction):
    interaction.user.id = 7
    invoke_command("update_crypto", "tst", "website", "https://new.example.com")
    return interaction.followup.send.call_args.kwargs["view"]


def test_info_shows_readable_coin_card(application, interaction, invoke_command):
    application.info = Mock(
        return_value=CoinInfo(
            "TST",
            "Test Coin",
            [("Network", "ETH ERC-20"), ("Website", "https://example.com"), ("Contract address", "0xabc")],
            [("CoinMarketCap", "https://coinmarketcap.com/currencies/test-coin/")],
        )
    )

    invoke_command("info", "tst")

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


def test_info_attaches_metadata_that_exceeds_embed_limits(application, interaction, invoke_command):
    info = CoinInfo("TST", "Test Coin", [("Description", "x" * 2100)], [])
    application.info = Mock(return_value=info)

    invoke_command("info", "TST")

    attachment = interaction.followup.send.call_args.kwargs["file"]
    assert attachment.filename == "info.txt"
    assert attachment.fp.read().decode("utf-8") == info.as_text()


def test_info_explains_unknown_coin(application, interaction, invoke_command):
    application.info = Mock(side_effect=CoinInfoError("Unknown coin: MISSING"))

    invoke_command("info", "missing")

    interaction.followup.send.assert_awaited_once_with("Unknown coin: MISSING", ephemeral=False)


def test_wen_offers_choices_and_uses_shared_reply(adapter, application, interaction, discord_context, invoke_command):
    application.wen = Mock(return_value=WenReply("HODL"))
    command = adapter.tree.get_command("wen")

    invoke_command("wen", "moon")

    assert [choice.value for choice in command.parameters[0].choices] == ["moon", "lambo", "aston"]
    application.wen.assert_called_once_with(discord_context, "moon")
    interaction.response.send_message.assert_awaited_once_with("HODL")
    interaction.followup.send.assert_not_awaited()


@pytest.mark.parametrize(
    "upload_error",
    [None, discord.HTTPException(SimpleNamespace(status=413, reason="Payload Too Large"), "File too large")],
    ids=["successful-upload", "failed-upload"],
)
def test_wen_replies_and_closes_optional_audio(application, interaction, moon_audio, invoke_command, upload_error):
    application.wen = Mock(return_value=WenReply("HODL", moon_audio))
    interaction.followup.send.side_effect = upload_error

    invoke_command("wen", "moon")

    interaction.response.send_message.assert_awaited_once_with("HODL")
    attachment = interaction.followup.send.call_args.kwargs["file"]
    assert attachment.filename == "wen_moon.ogg"
    assert attachment.fp.closed


def test_ethgas_shows_gas_tiers_in_a_card(application, interaction, discord_context, gas_prices, invoke_command):
    application.ethgas = Mock(return_value=gas_prices)

    invoke_command("ethgas")

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


def test_ethgas_explains_missing_configuration(interaction, invoke_command):
    invoke_command("ethgas")

    interaction.followup.send.assert_awaited_once_with(
        "Ethereum gas prices are not configured. Set ETHERSCAN_API_KEY to use /ethgas."
    )


def test_check_notifications_replies_privately(application, interaction, invoke_command):
    response = "TST at $12.0\n"
    application.check_notifications = Mock(return_value=response)

    invoke_command("check_notifications")

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    interaction.followup.send.assert_awaited_once_with(response, ephemeral=True)


def test_check_notifications_attaches_long_lists_privately(application, interaction, invoke_command):
    long_response = "TST at $12.0\n" * 200
    application.check_notifications = Mock(return_value=long_response)

    invoke_command("check_notifications")

    reply = interaction.followup.send.call_args
    attachment = reply.kwargs["file"]
    assert reply.kwargs["ephemeral"] is True
    assert attachment.filename == "notifications.txt"
    assert attachment.fp.read().decode("utf-8") == long_response


def test_delete_notification_replies_privately(application, interaction, discord_context, invoke_command):
    response = "Notification for TST deleted"
    application.delete_notification = Mock(return_value=response)

    invoke_command("delete_notification", "tst")

    application.delete_notification.assert_called_once_with(discord_context, "tst")
    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    interaction.followup.send.assert_awaited_once_with(response, ephemeral=True)


@pytest.mark.parametrize("command_name", ["notify_me", "dont_notify_me"])
def test_group_preference_commands_delegate_and_reply_privately(
    adapter, application, interaction, discord_context, invoke_command, command_name
):
    update = Mock(return_value="Preference saved")
    setattr(application, command_name, update)

    invoke_command(command_name)

    assert adapter.tree.get_command(command_name).guild_only is True
    update.assert_called_once_with(discord_context)
    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    interaction.followup.send.assert_awaited_once_with("Preference saved", ephemeral=True)


@pytest.mark.parametrize("command_name", ["notify_me", "dont_notify_me"])
def test_group_preference_commands_reject_direct_messages(application, interaction, invoke_command, command_name):
    interaction.guild_id = None
    update = Mock()
    setattr(application, command_name, update)

    invoke_command(command_name)

    update.assert_not_called()
    interaction.response.send_message.assert_awaited_once_with(
        "Use this command in a server channel or thread.", ephemeral=True
    )
    interaction.response.defer.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (GroupNotificationError("Group notifications are not configured."), "Group notifications are not configured."),
        (
            sqlite3.OperationalError("Disk unavailable"),
            "Could not save your group notification preference. Try again later.",
        ),
    ],
    ids=["not-configured", "database-unavailable"],
)
def test_group_preference_failures_reply_privately(application, interaction, invoke_command, error, expected):
    application.notify_me = Mock(side_effect=error)

    invoke_command("notify_me")

    interaction.followup.send.assert_awaited_once_with(expected, ephemeral=True)


def test_checker_skips_alert_canceled_during_user_lookup(
    adapter, alert_application, recipient, discord_context, triggered_alert, run_async
):
    async def cancel_during_user_lookup(_user_id):
        alert_application.delete_notification(discord_context, triggered_alert.coin)
        return recipient

    adapter.fetch_user.side_effect = cancel_during_user_lookup

    run_async(adapter.check_price_notifications())

    recipient.send.assert_not_awaited()
    assert alert_application.check_notifications(discord_context) == "No notifications set"


def test_price_notify_registers_user_and_confirms_privately(alert_application, interaction, invoke_command):
    invoke_command("price_notify", "tst", 12.0)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    confirmation = interaction.followup.send.call_args
    assert "Created notification for TST at $12.0" in confirmation.args[0]
    assert confirmation.kwargs["ephemeral"] is True
    assert alert_application.price_alerts.has_user(str(interaction.user.id))


def test_price_notify_explains_invalid_target(alert_application, interaction, invoke_command):
    invoke_command("price_notify", "TST", -1)

    confirmation = interaction.followup.send.call_args
    assert "positive, finite" in confirmation.args[0]
    assert confirmation.kwargs["ephemeral"] is True


def test_blocked_dm_is_retained_and_retried(adapter, alert_application, recipient, triggered_alert, run_async):
    recipient.send.side_effect = discord.Forbidden(
        SimpleNamespace(status=403, reason="Forbidden"), "Cannot send messages to this user"
    )

    run_async(adapter.check_price_notifications())

    assert alert_application.price_alerts.due_notifications() == [triggered_alert]
    recipient.send.side_effect = None
    recipient.send.reset_mock()

    run_async(adapter.check_price_notifications())
    run_async(adapter.check_price_notifications())

    recipient.send.assert_awaited_once_with(triggered_alert.message())
    assert alert_application.price_alerts.due_notifications() == []
    adapter.fetch_user.assert_awaited_with(triggered_alert.user_id)


def test_alert_scheduler_waits_for_ready_and_stops_on_close(adapter, alert_application, run_async):
    ready = asyncio.Event()
    adapter.wait_until_ready = AsyncMock(side_effect=ready.wait)
    adapter.tree.sync = AsyncMock()
    alert_application.price_alerts.due_notifications = Mock(return_value=[])

    run_async(adapter.setup_hook())
    run_async(asyncio.sleep(0))

    task = adapter.check_price_notifications.get_task()
    assert adapter.check_price_notifications.is_running()
    assert adapter.check_price_notifications.minutes == 15
    adapter.wait_until_ready.assert_awaited_once()
    alert_application.price_alerts.due_notifications.assert_not_called()

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
    application,
    interaction,
    discord_context,
    market_lookup,
    market_quote,
    invoke_command,
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

    invoke_command("price", " tst ")

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

    assert application.coins(discord_context) == "Known coins:\nTST ; NEW"
    saved_coins = json.loads(application.crypto_path.read_text(encoding="utf-8"))
    assert saved_coins["TST"] == {"cmc_id": "42"}
    assert saved_coins["NEW"]["cmc_id"] == "43"
    assert saved_coins["NEW"]["cmc_slug"] == "new-coin"
    with pytest.raises(CoinCreationError, match="already known"):
        application.add_coin(candidate)


@pytest.mark.parametrize(
    ("command_name", "arguments"),
    [
        ("new_crypto", ("NEW",)),
        ("update_crypto", ("TST", "website", "https://example.com")),
        ("new_media_command", ("frog", None)),
    ],
    ids=["add-coin", "update-coin", "create-media-command"],
)
def test_admin_commands_reject_non_admins(application, interaction, invoke_command, command_name, arguments):
    invoke_command(command_name, *arguments)

    reply = interaction.response.send_message.call_args
    assert "Only admins" in reply.args[0]
    assert reply.kwargs["ephemeral"] is True
    assert "NEW" not in application.cryptos
    assert not application.crypto_path.exists()


def test_new_media_command_registers_and_sends_image(
    adapter, media_application, interaction, image_upload, invoke_command
):
    interaction.user.id = 7
    adapter.tree.sync = AsyncMock()

    invoke_command("new_media_command", " FROG ", image_upload, "memes")

    interaction.response.defer.assert_awaited_once_with(ephemeral=True, thinking=True)
    interaction.followup.send.assert_awaited_once_with("Created /frog. Use it to send the saved image.", ephemeral=True)
    adapter.tree.sync.assert_awaited_once_with(guild=discord.Object(id=123))
    assert adapter.tree.get_command("frog").parameters == []

    interaction.user.id = 8
    invoke_command("frog")

    attachment = interaction.followup.send.call_args.kwargs["file"]
    assert attachment.filename == "frog.png"
    assert attachment.fp.closed


def test_saved_media_commands_are_registered_on_restart(media_application, interaction, run_async):
    command = media_application.prepare_media_command("frog", "frog.png", "memes", 5)
    media_application.add_media_command(command, b"image")
    client = DiscordAdapter(media_application, {7}, None)
    client.tree.sync = AsyncMock()
    try:
        run_async(client.setup_hook())
        assert client.tree.get_command("frog") is not None
        client.tree.sync.assert_awaited_once_with()
        (media_application.media_commands.directory / command.filename).unlink()

        run_async(client.tree.get_command("frog").callback(interaction))

        interaction.followup.send.assert_awaited_once_with(
            "Could not send the saved image. Ask an admin to check its file."
        )
    finally:
        run_async(client.close())


@pytest.mark.parametrize("name", ["coins", "frog"], ids=["built-in-command", "saved-command"])
def test_media_command_rejects_duplicate_names(
    adapter, media_application, interaction, image_upload, invoke_command, name
):
    saved = media_application.prepare_media_command("frog", "frog.png", "memes", 5)
    media_application.add_media_command(saved, b"image")
    interaction.user.id = 7
    adapter.tree.sync = AsyncMock()

    invoke_command("new_media_command", name, image_upload)

    image_upload.read.assert_not_awaited()
    adapter.tree.sync.assert_not_awaited()
    assert "already exists" in interaction.followup.send.call_args.args[0]


@pytest.mark.parametrize("failure", ["download", "save"])
def test_media_upload_failure_does_not_register_command(
    adapter, media_application, interaction, image_upload, invoke_command, failure
):
    interaction.user.id = 7
    adapter.tree.sync = AsyncMock()
    if failure == "download":
        image_upload.read.side_effect = discord.HTTPException(
            SimpleNamespace(status=404, reason="Not Found"), "Missing"
        )
    else:
        media_application.add_media_command = Mock(side_effect=OSError("Disk unavailable"))

    invoke_command("new_media_command", "frog", image_upload)

    interaction.followup.send.assert_awaited_once_with("Could not save the image. Try again later.", ephemeral=True)
    assert adapter.tree.get_command("frog") is None
    assert media_application.media_commands.commands() == ()
    adapter.tree.sync.assert_not_awaited()


def test_media_sync_failure_keeps_saved_command_for_restart(
    adapter, media_application, interaction, image_upload, invoke_command
):
    interaction.user.id = 7
    adapter.tree.sync = AsyncMock(
        side_effect=discord.HTTPException(SimpleNamespace(status=503, reason="Unavailable"), "Try later")
    )

    invoke_command("new_media_command", "frog", image_upload)

    assert adapter.tree.get_command("frog") is not None
    assert media_application.media_commands.commands()[0].name == "frog"
    assert "Saved /frog" in interaction.followup.send.call_args.args[0]
    assert "Restart the bot" in interaction.followup.send.call_args.args[0]


def test_list_commands_uses_shared_listing(application, interaction, discord_context, invoke_command):
    application.list_commands = Mock(return_value="Custom commands in memes:\n/frog")

    invoke_command("list_commands", "memes")

    application.list_commands.assert_called_once_with(discord_context, "memes")
    interaction.response.defer.assert_awaited_once_with(thinking=True)
    interaction.followup.send.assert_awaited_once_with("Custom commands in memes:\n/frog", ephemeral=False)


def test_new_crypto_confirmation_calls_shared_save(application, interaction, new_coin, invoke_command, run_async):
    interaction.user.id = 7
    application.prepare_new_coin = Mock(return_value=new_coin)
    application.add_coin = Mock()
    invoke_command("new_crypto", "NEW")
    confirmation_view = interaction.followup.send.call_args.kwargs["view"]

    run_async(confirmation_view.children[0].callback(interaction))

    application.prepare_new_coin.assert_called_once_with("NEW")
    application.add_coin.assert_called_once_with(new_coin)
    interaction.response.edit_message.assert_awaited_once_with(
        content="Success. NEW has been added to the bot.", view=None
    )


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


def test_update_crypto_confirmation_calls_shared_save(application, interaction, pending_update, run_async):
    application.update_coin = Mock()

    run_async(pending_update.children[0].callback(interaction))

    application.update_coin.assert_called_once_with(pending_update.change)
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


def test_update_crypto_explains_unknown_coin(interaction, invoke_command):
    interaction.user.id = 7

    invoke_command("update_crypto", "missing", "website", "https://example.com")

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


def test_update_crypto_attaches_long_previews(application, interaction, invoke_command):
    interaction.user.id = 7
    old_value = "x" * 2100
    application.cryptos["TST"]["INFO"] = {"custom_note": old_value}

    invoke_command("update_crypto", "TST", "custom_note", "Shorter note")

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
