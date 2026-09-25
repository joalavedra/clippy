"""Short-lived signed tokens for protected media URLs."""

from __future__ import annotations

import hashlib
import hmac
import time


def sign_media_token(secret: str, file_key: str, expires_at: int) -> str:
    payload = f"{file_key}\n{expires_at}".encode()
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"{expires_at}.{digest}"


def verify_media_token(
    secret: str,
    file_key: str,
    token: str,
    now: int | None = None,
) -> bool:
    try:
        expires_text, provided_digest = token.split(".", 1)
        expires_at = int(expires_text)
    except (ValueError, AttributeError):
        return False
    if expires_at <= (int(time.time()) if now is None else now):
        return False
    expected = sign_media_token(secret, file_key, expires_at).split(".", 1)[1]
    return hmac.compare_digest(provided_digest, expected)
