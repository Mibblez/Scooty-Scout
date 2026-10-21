import pytest

from bot_application import CoinInfoError


@pytest.fixture
def coin_record(application):
    record = {
        "INFO": {"contract_id": "0xabc", "chain": "ETH ERC-20", "website": "https://example.com"},
        "cmc_name": "Test Coin",
        "cmc_slug": "canonical-test-coin",
    }
    application.cryptos["TST"] = record
    return record


def test_info_formats_saved_metadata(application, coin_record, discord_context, market_lookup):
    info = application.info(discord_context, " tst ")

    assert info.as_text() == (
        "Test Coin (TST)\n\n"
        "Network: ETH ERC-20\n"
        "Website: https://example.com\n"
        "Contract address: 0xabc\n\n"
        "CoinMarketCap: https://coinmarketcap.com/currencies/canonical-test-coin/"
    )
    market_lookup.assert_not_called()


def test_info_omits_empty_native_coin_fields(application, coin_record, discord_context):
    coin_record["INFO"] = {
        "contract_id": None,
        "chain": None,
        "website": "https://example.com",
        "custom_note": "Native coin",
    }

    info = application.info(discord_context, "TST")

    assert info.fields == [("Website", "https://example.com"), ("Custom Note", "Native coin")]
    assert info.links == []


@pytest.mark.parametrize("chain", ["BSC", "BNB BEP20"], ids=["legacy-bsc", "new-bnb-token"])
def test_info_keeps_bnb_explorer_links(application, coin_record, discord_context, chain):
    coin_record["INFO"]["chain"] = chain

    info = application.info(discord_context, "TST")

    assert info.links == [
        ("BscScan", "https://www.bscscan.com/address/0xabc"),
        ("DEXTools", "https://www.dextools.io/app/bsc/pair-explorer/0xabc"),
    ]


def test_info_supports_catalog_without_slug(application, coin_record, discord_context):
    del coin_record["cmc_slug"]

    info = application.info(discord_context, "TST")

    assert info.links == [("CoinMarketCap", "https://coinmarketcap.com/currencies/test-coin/")]


@pytest.mark.parametrize(
    ("symbol", "error"), [("", "Usage"), ("missing", "Unknown coin")], ids=["missing-symbol", "unknown-symbol"]
)
def test_info_rejects_invalid_requests(application, discord_context, market_lookup, symbol, error):
    with pytest.raises(CoinInfoError, match=error):
        application.info(discord_context, symbol)

    market_lookup.assert_not_called()


def test_info_handles_missing_metadata(application, discord_context):
    info = application.info(discord_context, "TST")

    assert info.as_text() == "TST\n\nNo additional information available."
