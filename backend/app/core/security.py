"""
Security utilities for the online mode WebSocket.
- Password validation against SERVER_PASSWORD env var
- Rate limiting per IP (in-memory, resets every 60 seconds)
- Session token issuance and validation
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from app.core.config import settings

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

@dataclass
class _RateEntry:
    attempts: int = 0
    window_start: float = field(default_factory=time.monotonic)


_rate_store: dict[str, _RateEntry] = defaultdict(_RateEntry)
_WINDOW_SECONDS = 60


def check_rate_limit(ip: str) -> bool:
    """
    Return True if the IP is allowed to attempt auth.
    Return False if they've exceeded the limit (block them).
    """
    entry = _rate_store[ip]
    now = time.monotonic()

    if now - entry.window_start >= _WINDOW_SECONDS:
        entry.attempts = 0
        entry.window_start = now

    if entry.attempts >= settings.auth_rate_limit:
        return False

    entry.attempts += 1
    return True


def reset_rate_limit(ip: str) -> None:
    """Called on successful auth — reset the counter for this IP."""
    if ip in _rate_store:
        _rate_store[ip].attempts = 0


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

def validate_password(password: str) -> bool:
    """Constant-time-safe comparison to prevent timing attacks."""
    import hmac
    return hmac.compare_digest(password, settings.server_password)


# ---------------------------------------------------------------------------
# Session tokens
# ---------------------------------------------------------------------------

@dataclass
class Session:
    token: str
    ip: str
    created_at: float = field(default_factory=time.monotonic)
    player_name: str = ""


_sessions: dict[str, Session] = {}


def create_session(ip: str, player_name: str = "") -> str:
    token = str(uuid.uuid4())
    _sessions[token] = Session(token=token, ip=ip, player_name=player_name)
    return token


def validate_session(token: str) -> Session | None:
    session = _sessions.get(token)
    if session is None:
        return None
    timeout = settings.session_timeout_minutes * 60
    if time.monotonic() - session.created_at > timeout:
        del _sessions[token]
        return None
    return session


def invalidate_session(token: str) -> None:
    _sessions.pop(token, None)


def get_all_sessions() -> dict[str, Session]:
    return dict(_sessions)
