import json
from unittest.mock import Mock

import pytest

import json_storage
from bot_application import CoinUpdateError


@pytest.mark.parametrize(
    ("field", "value"),
    [("website", "https://new.example.com"), ("custom_note", "Updated information")],
    ids=["existing-field", "new-field"],
)
def test_confirmed_update_preserves_other_coin_data(application, discord_context, field, value):
    original = {"INFO": {"website": "https://old.example.com"}, "cmc_id": "42", "cmc_name": "Test Coin"}
    application.cryptos["TST"] = original

    change = application.prepare_coin_update(" tst ", f" {field} ", f" {value} ")

    assert change.symbol == "TST"
    assert change.field == field
    assert change.value == value
    assert original["INFO"] == {"website": "https://old.example.com"}
    assert not application.crypto_path.exists()

    application.update_coin(change)

    saved = json.loads(application.crypto_path.read_text(encoding="utf-8"))
    assert saved == application.cryptos
    assert saved["TST"] == {**original, "INFO": {**original["INFO"], field: value}}
    assert value in application.info(discord_context, "TST").as_text()


@pytest.mark.parametrize(
    ("symbol", "field", "value", "error"),
    [
        ("", "website", "https://example.com", "Usage"),
        ("missing", "website", "https://example.com", "unknown coin MISSING"),
        ("TST", " ", "https://example.com", "Provide a metadata field"),
        ("TST", "website", " ", "non-empty value"),
    ],
    ids=["missing-symbol", "unknown-symbol", "missing-field", "missing-value"],
)
def test_invalid_update_leaves_catalog_unchanged(application, symbol, field, value, error):
    with pytest.raises(CoinUpdateError, match=error):
        application.prepare_coin_update(symbol, field, value)

    assert application.cryptos == {"TST": {"cmc_id": "42"}}
    assert not application.crypto_path.exists()


def test_updates_to_different_fields_can_both_be_saved(application):
    website = application.prepare_coin_update("TST", "website", "https://example.com")
    network = application.prepare_coin_update("TST", "chain", "ETH ERC-20")

    application.update_coin(website)
    application.update_coin(network)

    assert application.cryptos["TST"]["INFO"] == {"website": website.value, "chain": network.value}


def test_update_rejects_a_stale_preview(application):
    first = application.prepare_coin_update("TST", "website", "https://first.example.com")
    stale = application.prepare_coin_update("TST", "website", "https://stale.example.com")
    application.update_coin(first)

    with pytest.raises(CoinUpdateError, match="changed after your preview"):
        application.update_coin(stale)

    saved = json.loads(application.crypto_path.read_text(encoding="utf-8"))
    assert saved["TST"]["INFO"]["website"] == first.value
    assert application.cryptos == saved


def test_failed_save_preserves_live_and_saved_catalog(application, monkeypatch):
    first = application.prepare_coin_update("TST", "website", "https://first.example.com")
    application.update_coin(first)
    saved_before = application.crypto_path.read_text(encoding="utf-8")
    change = application.prepare_coin_update("TST", "website", "https://new.example.com")
    monkeypatch.setattr(json_storage.os, "replace", Mock(side_effect=OSError("Disk unavailable")))

    with pytest.raises(OSError, match="Disk unavailable"):
        application.update_coin(change)

    assert application.crypto_path.read_text(encoding="utf-8") == saved_before
    assert application.cryptos == json.loads(saved_before)
    assert list(application.crypto_path.parent.glob(".cryptos-*.json")) == []
