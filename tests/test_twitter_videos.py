"""Twitter/X downloads using a fake downloader, without network requests."""

from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock

import pytest

import twitter_videos
from media_commands import MAX_MEDIA_BYTES, MediaCommandError


@pytest.fixture
def downloader(monkeypatch):
    client = Mock()

    def create(options):
        client.options = options
        return nullcontext(client)

    def save(_urls):
        path = Path(client.options["outtmpl"] % {"ext": "mp4"})
        path.write_bytes(b"video")

    client.download.side_effect = save
    monkeypatch.setattr(twitter_videos.yt_dlp, "YoutubeDL", create)
    return client


@pytest.mark.parametrize(
    ("url", "canonical"),
    [
        ("https://x.com/ada/status/123?s=20", "https://x.com/i/status/123"),
        ("http://twitter.com/i/status/123", "https://x.com/i/status/123"),
        ("https://mobile.twitter.com/i/web/status/123/video/2", "https://x.com/i/status/123/video/2"),
    ],
)
def test_public_video_links_download_to_temporary_storage(downloader, url, canonical):
    assert twitter_videos.download_twitter_video(url) == b"video"

    downloader.download.assert_called_once_with([canonical])
    assert not Path(downloader.options["outtmpl"]).parent.exists()


@pytest.mark.parametrize(
    "url",
    ["https://example.com/ada/status/123", "https://x.com@localhost/ada/status/123", "https://x.com/ada"],
)
def test_invalid_video_urls_are_rejected_before_downloading(downloader, url):
    with pytest.raises(MediaCommandError, match="Twitter/X post URL"):
        twitter_videos.download_twitter_video(url)

    downloader.download.assert_not_called()


def test_download_failure_cleans_up_temporary_files(downloader):
    downloader.download.side_effect = twitter_videos.yt_dlp.utils.DownloadError("Video unavailable")

    with pytest.raises(MediaCommandError, match="Could not download"):
        twitter_videos.download_twitter_video("https://x.com/ada/status/123")

    assert not Path(downloader.options["outtmpl"]).parent.exists()


@pytest.mark.parametrize("size_source", ["progress", "saved-file"])
def test_oversized_download_is_stopped_and_cleaned_up(downloader, size_source):
    def exceed_limit(_urls):
        if size_source == "progress":
            hook = downloader.options["progress_hooks"][0]
            hook({"downloaded_bytes": MAX_MEDIA_BYTES + 1})
        else:
            path = Path(downloader.options["outtmpl"] % {"ext": "mp4"})
            path.write_bytes(b"v" * (MAX_MEDIA_BYTES + 1))

    downloader.download.side_effect = exceed_limit

    with pytest.raises(MediaCommandError, match="8 MiB"):
        twitter_videos.download_twitter_video("https://x.com/ada/status/123")

    assert not Path(downloader.options["outtmpl"]).parent.exists()


def test_missing_video_file_does_not_create_a_command(downloader):
    downloader.download.side_effect = None

    with pytest.raises(MediaCommandError, match="Could not download an MP4"):
        twitter_videos.download_twitter_video("https://x.com/ada/status/123")
