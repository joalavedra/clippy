from pathlib import Path

import pytest

from clipping import engine
from clipping.ingest_errors import (
    DownloadError,
    classify_download_error,
    user_message,
)


@pytest.mark.parametrize(
    ("detail", "reason"),
    [
        ("Sign in to confirm you're not a bot", "bot_check"),
        ("Private video", "private_or_removed"),
        ("This video is not available in your country", "geo_blocked"),
        ("This content requires authentication", "login_required"),
        ("HTTP Error 403: Forbidden", "forbidden"),
        ("<urlopen error [Errno 101]>", "network"),
        ("unexpected yt-dlp failure", "unknown"),
    ],
)
def test_classify_download_error(detail, reason):
    assert classify_download_error(RuntimeError(detail)) == reason


def test_bot_check_message_mentions_cookie_export():
    error = DownloadError("bot_check", detail="not a bot")
    message = user_message(error)
    assert "CLIPPY_YTDLP_COOKIES" in message
    assert "cookies.txt" in message


def test_download_retries_rotate_youtube_clients(tmp_path, monkeypatch):
    attempts = []
    sleeps = []
    output = tmp_path / "video.mp4"

    class FakeYoutubeDL:
        def __init__(self, options):
            attempts.append(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download=False):
            return {"height": 720, "vcodec": "h264"}

        def download(self, urls):
            if len(attempts) < 3:
                raise RuntimeError("urlopen error: temporary failure")
            Path(output).write_bytes(b"video")

    monkeypatch.setattr(engine, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(engine.time, "sleep", sleeps.append)

    engine.download_video(
        "https://youtube.example/video",
        str(output),
        retries=2,
    )

    assert len(attempts) == 3
    assert [
        item["extractor_args"]["youtube"][0] for item in attempts
    ] == [
        "player_client=android,web",
        "player_client=web_safari,web",
        "player_client=tv,web",
    ]
    assert sleeps == [2, 4]


def test_private_download_error_fails_without_retry(tmp_path, monkeypatch):
    attempts = []

    class FakeYoutubeDL:
        def __init__(self, options):
            attempts.append(options)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def extract_info(self, url, download=False):
            raise RuntimeError("Private video")

        def download(self, urls):
            raise AssertionError("download should not be reached")

    monkeypatch.setattr(engine, "YoutubeDL", FakeYoutubeDL)

    with pytest.raises(DownloadError) as raised:
        engine.download_video(
            "https://youtube.example/private",
            str(tmp_path / "video.mp4"),
            retries=2,
        )

    assert raised.value.reason == "private_or_removed"
    assert len(attempts) == 1
