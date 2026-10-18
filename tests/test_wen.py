"""Shared /wen response selection without platform APIs."""

import pytest

import wen


@pytest.mark.parametrize("thing", ["moon", "lambo", "aston"])
def test_wen_chooses_from_the_requested_responses(monkeypatch, tmp_path, thing):
    monkeypatch.setattr(wen, "MOON_AUDIO_PATH", tmp_path / "missing.ogg")

    reply = wen.get_wen_reply(f" {thing.upper()} ")

    assert reply.text in wen.WEN_REPLIES[thing]
    assert reply.audio_path is None


def test_wen_ignores_unsupported_topics():
    assert wen.get_wen_reply("rocket") is None


def test_wen_only_uses_audio_for_moon(moon_audio, monkeypatch):
    monkeypatch.setattr(wen, "MOON_AUDIO_PATH", moon_audio)

    assert wen.get_wen_reply("moon").audio_path == moon_audio
    assert wen.get_wen_reply("lambo").audio_path is None
    assert wen.get_wen_reply("aston").audio_path is None
