"""Classified errors raised while ingesting source media."""

from __future__ import annotations

REASONS = {
    "bot_check",
    "private_or_removed",
    "geo_blocked",
    "login_required",
    "forbidden",
    "network",
    "unknown",
}


class DownloadError(RuntimeError):
    """A source download failure with a stable user-facing classification."""

    def __init__(
        self,
        reason: str,
        source_id: str | None = None,
        detail: str = "",
    ):
        self.reason = reason if reason in REASONS else "unknown"
        self.source_id = source_id
        self.detail = detail
        super().__init__(detail or self.reason)


def classify_download_error(exc: Exception) -> str:
    """Classify common yt-dlp/network failures without exposing implementation details."""
    message = str(exc).lower()
    if "sign in to confirm you're not a bot" in message or "not a bot" in message:
        return "bot_check"
    if (
        "not available in your country" in message
        or "geo-restricted" in message
        or "geo restricted" in message
        or "geoblock" in message
    ):
        return "geo_blocked"
    if (
        "private video" in message
        or "video unavailable" in message
        or "has been removed" in message
        or "this video is not available" in message
    ):
        return "private_or_removed"
    if (
        "login required" in message
        or "requested content is not available, rate-limit reached" in message
        or "requires authentication" in message
    ):
        return "login_required"
    if "http error 403" in message or "forbidden" in message:
        return "forbidden"
    if (
        "urlopen error" in message
        or "timed out" in message
        or "connection reset" in message
        or "temporary failure in name resolution" in message
    ):
        return "network"
    return "unknown"


def user_message(error: DownloadError) -> str:
    """Return actionable guidance for a classified download failure."""
    messages = {
        "bot_check": (
            "YouTube asked for a bot check. Set CLIPPY_YTDLP_COOKIES to a "
            "Netscape cookies.txt exported from a logged-in browser and retry."
        ),
        "private_or_removed": (
            "The source is private, unavailable, or has been removed. "
            "Check the URL and source visibility."
        ),
        "geo_blocked": (
            "The source is blocked in this country or region. "
            "Use an accessible source or retry from an allowed region."
        ),
        "login_required": (
            "The source requires authentication. Set CLIPPY_YTDLP_COOKIES "
            "to a logged-in Netscape cookies.txt file and retry."
        ),
        "forbidden": (
            "The source server refused access. Check permissions or provide "
            "a logged-in cookies file."
        ),
        "network": (
            "The source could not be reached due to a temporary network "
            "problem. Retry shortly."
        ),
        "unknown": "The source download failed. Check the URL and try again.",
    }
    message = messages.get(error.reason, messages["unknown"])
    if error.reason == "unknown" and error.detail:
        return f"{message} Details: {error.detail}"
    return message
