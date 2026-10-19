"""Custom media storage and listing without platform APIs."""

import json
from unittest.mock import Mock

import pytest

import media_commands
from bot_application import BotApplication
from media_commands import MAX_MEDIA_BYTES, MediaCommandError, MediaCommands


def test_media_commands_persist_and_list_by_group(media_application, discord_context):
    frog = media_application.prepare_media_command(" FROG ", "upload.PNG", " Memes ", 5)
    chart = media_application.prepare_media_command("chart", "chart.jpg", "charts", 5)
    media_application.add_media_command(frog, b"image")
    media_application.add_media_command(chart, b"chart")

    reopened = BotApplication({}, media_path=media_application.media_commands.directory)

    assert reopened.media_commands.commands() == (chart, frog)
    assert (reopened.media_commands.directory / frog.filename).read_bytes() == b"image"
    assert reopened.list_commands(discord_context) == "Custom media commands:\ncharts: /chart\nmemes: /frog"
    assert reopened.list_commands(discord_context, " MEMES ") == "Custom commands in memes:\n/frog"
    with pytest.raises(MediaCommandError, match="already exists"):
        reopened.prepare_media_command("frog", "other.png", "memes", 5)
    with pytest.raises(MediaCommandError, match="Known groups: charts, memes"):
        reopened.list_commands(discord_context, "missing")


@pytest.mark.parametrize(
    ("name", "filename", "group", "size"),
    [
        ("../escape", "frog.png", "memes", 5),
        ("x" * 33, "frog.png", "memes", 5),
        ("frog", "frog.png", "../escape", 5),
        ("frog", "script.py", "memes", 5),
        ("frog", "frog.png", "memes", 0),
        ("frog", "frog.png", "memes", MAX_MEDIA_BYTES + 1),
    ],
    ids=["unsafe-name", "long-name", "unsafe-group", "unsupported-file", "empty-file", "large-file"],
)
def test_invalid_media_request_does_not_create_files(media_application, name, filename, group, size):
    with pytest.raises(MediaCommandError):
        media_application.prepare_media_command(name, filename, group, size)

    assert not media_application.media_commands.directory.exists()


def test_media_save_failure_keeps_existing_commands(media_application, monkeypatch):
    store = media_application.media_commands
    frog = store.prepare("frog", "frog.png", "memes", 5)
    store.add(frog, b"image")
    before = store.catalog_path.read_bytes()
    chart = store.prepare("chart", "chart.png", "charts", 5)
    monkeypatch.setattr(media_commands.os, "replace", Mock(side_effect=OSError("Disk unavailable")))

    with pytest.raises(OSError, match="Disk unavailable"):
        store.add(chart, b"chart")

    assert store.catalog_path.read_bytes() == before
    assert store.commands() == (frog,)
    assert sorted(path.name for path in store.directory.iterdir()) == ["commands.json", "frog.png"]


def test_saved_media_paths_cannot_escape_the_directory(tmp_path):
    catalog = tmp_path / "commands.json"
    catalog.write_text(json.dumps({"frog": {"group": "memes", "filename": "../frog.png"}}), encoding="utf-8")

    with pytest.raises(MediaCommandError, match="Invalid media command catalog"):
        MediaCommands(tmp_path)


def test_media_add_validates_downloaded_content(media_application):
    command = media_application.prepare_media_command("frog", "frog.png", "memes", 5)

    with pytest.raises(MediaCommandError, match="non-empty"):
        media_application.add_media_command(command, b"")

    assert not media_application.media_commands.directory.exists()


def test_empty_media_catalog_has_a_readable_listing(media_application, discord_context):
    assert media_application.list_commands(discord_context) == "No custom media commands have been added yet."
