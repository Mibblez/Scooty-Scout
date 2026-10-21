"""Download public Twitter/X videos."""

import logging
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import yt_dlp

from media_commands import MAX_MEDIA_BYTES, MediaCommandError

logger = logging.getLogger("scooty_scout")


def twitter_video_url(url: str) -> str:
    """Normalize post links and copied video addresses, preserving video selection."""
    try:
        parsed = urlsplit(url.strip())
    except ValueError as error:
        raise MediaCommandError("Provide a Twitter/X post URL containing a video.") from error
    hosts = {"twitter.com", "www.twitter.com", "mobile.twitter.com", "x.com", "www.x.com", "mobile.x.com"}
    match = re.fullmatch(
        r"/(?:[A-Za-z0-9_]+/status|i/web/status|statuses)/" r"(?P<post_id>[0-9]+)(?P<video_path>/video/[1-9][0-9]*)?/?",
        parsed.path,
    )
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in hosts or match is None:
        raise MediaCommandError("Provide a Twitter/X post URL containing a video.")
    return f"https://x.com/i/status/{match['post_id']}{match['video_path'] or ''}"


def _check_download_size(progress: dict) -> None:
    if progress.get("downloaded_bytes", 0) > MAX_MEDIA_BYTES:
        raise MediaCommandError("The video exceeds the 8 MiB media limit.")


def download_twitter_video(url: str) -> bytes:
    url = twitter_video_url(url)
    with TemporaryDirectory(prefix="crypto-tracker-video-") as directory:
        direct_mp4 = (
            "[ext=mp4][protocol^=http][protocol!*=dash]"
            f"[filesize<=?{MAX_MEDIA_BYTES}][filesize_approx<=?{MAX_MEDIA_BYTES}]"
        )
        options = {
            "outtmpl": str(Path(directory) / "video.%(ext)s"),
            # Download a direct MP4 to avoid an ffmpeg merge.
            "format": f"best{direct_mp4}/bestvideo{direct_mp4}",
            "max_filesize": MAX_MEDIA_BYTES,
            "noplaylist": True,
            "playlist_items": "1",
            "socket_timeout": 15,
            "retries": 1,
            "extractor_retries": 1,
            "cachedir": False,
            "quiet": True,
            "no_warnings": True,
            "logger": logger,
            "progress_hooks": [_check_download_size],
        }
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([url])
        except yt_dlp.utils.DownloadError as error:
            raise MediaCommandError(
                "Could not download that video. Use a public Twitter/X post with an MP4 video up to 8 MiB."
            ) from error
        path = Path(directory) / "video.mp4"
        if not path.is_file():
            raise MediaCommandError("Could not download an MP4 video up to 8 MiB from that post.")
        if not 0 < path.stat().st_size <= MAX_MEDIA_BYTES:
            raise MediaCommandError("Videos must be non-empty and at most 8 MiB.")
        return path.read_bytes()
