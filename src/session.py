"""
Session management.

Sessions are held entirely in-memory using a thread-safe dict.
Each session has:
  - a random UUID token (opaque to the client)
  - a creation time and TTL for expiry
  - a conversation history list

No passwords or sensitive data are stored in sessions.
"""

import logging
import secrets
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Message:
    role: str   # "user" or "assistant"
    content: str


@dataclass
class Session:
    token: str
    created_at: float
    ttl: float          # seconds
    history: List[Message] = field(default_factory=list)
    _last_active: float = field(init=False)

    def __post_init__(self) -> None:
        self._last_active = self.created_at

    def is_expired(self) -> bool:
        return (time.monotonic() - self._last_active) > self.ttl

    def touch(self) -> None:
        """Reset the idle timer."""
        self._last_active = time.monotonic()

    def append(self, role: str, content: str) -> None:
        self.history.append(Message(role=role, content=content))
        self.touch()

    def seconds_remaining(self) -> float:
        elapsed = time.monotonic() - self._last_active
        return max(self.ttl - elapsed, 0.0)


class SessionStore:
    """
    Thread-safe in-memory store for active sessions.

    Tokens are 32 bytes of URL-safe random data (256-bit entropy).
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        self._ttl = ttl_seconds
        self._sessions: Dict[str, Session] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self) -> Session:
        token = secrets.token_urlsafe(32)
        session = Session(
            token=token,
            created_at=time.monotonic(),
            ttl=self._ttl,
        )
        with self._lock:
            self._sessions[token] = session
        logger.info("Session created (token prefix: %s…).", token[:8])
        return session

    def get(self, token: str) -> Optional[Session]:
        """Return a valid session or None if missing/expired."""
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if session.is_expired():
                del self._sessions[token]
                logger.info("Session expired (token prefix: %s…).", token[:8])
                return None
            return session

    def invalidate(self, token: str) -> bool:
        """Explicitly destroy a session (logout). Returns True if it existed."""
        with self._lock:
            existed = token in self._sessions
            self._sessions.pop(token, None)
        if existed:
            logger.info("Session invalidated (token prefix: %s…).", token[:8])
        return existed

    def purge_expired(self) -> int:
        """Remove all expired sessions. Returns count removed."""
        with self._lock:
            expired = [t for t, s in self._sessions.items() if s.is_expired()]
            for t in expired:
                del self._sessions[t]
        if expired:
            logger.debug("Purged %d expired session(s).", len(expired))
        return len(expired)

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for s in self._sessions.values() if not s.is_expired())
