"""Choose joke responses and optional audio for /wen."""

import random
from dataclasses import dataclass
from pathlib import Path

MOON_AUDIO_PATH = Path("media/wen_moon.ogg")
WEN_REPLIES = {
    "moon": ("Ask Musk Daddy\n\nhttps://twitter.com/elonmusk", "Soon", "HODL", "Ask Rob", "WEN MOON?"),
    "lambo": (
        "https://www.lamborghini.com/en-en/models/aventador/aventador-svj",
        "https://www.lamborghini.com/en-en/models/aventador/aventador-svj-roadster",
        "https://www.lamborghini.com/en-en/models/aventador/aventador-lp-780-4-ultimae",
        "https://www.lamborghini.com/en-en/models/aventador/aventador-lp-780-4-ultimae-roadster",
        "https://www.lamborghini.com/en-en/models/huracan/huracan-evo",
        "https://www.lamborghini.com/en-en/models/huracan/huracan-evo-spyder",
        "https://www.lamborghini.com/en-en/models/huracan/huracan-evo-rwd",
        "https://www.lamborghini.com/en-en/models/huracan/huracan-evo-rwd-spyder",
        "https://www.lamborghini.com/en-en/models/huracan/huracan-evo-fluo-capsule",
        "https://www.lamborghini.com/en-en/models/huracan/huracan-sto",
        "https://ezgo.txtsv.com/personal/golfcarts/freedom-rxv",
    ),
    "aston": (
        "https://www.astonmartin.com/en-us/models/aston-martin-valkyrie",
        "https://www.astonmartin.com/en-us/models/dbx",
        "https://www.astonmartin.com/en-us/models/new-vantage",
        "https://www.astonmartin.com/en-us/models/db11",
        "https://www.astonmartin.com/en-us/models/dbs-superleggera",
    ),
}


@dataclass(frozen=True)
class WenReply:
    text: str
    audio_path: Path | None = None


def get_wen_reply(thing: str) -> WenReply | None:
    thing = thing.strip().lower()
    replies = WEN_REPLIES.get(thing)
    if replies is None:
        return None
    audio_path = MOON_AUDIO_PATH if thing == "moon" and MOON_AUDIO_PATH.is_file() else None
    return WenReply(random.choice(replies), audio_path)
