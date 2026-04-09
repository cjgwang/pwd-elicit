"""
Authentication logic.

- Password verification against a bcrypt hash stored in env/config.
- Rate limiting / lockout after repeated failures per client key.
- No plaintext passwords are ever stored or logged.
"""

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict

import bcrypt

from .config import Config

logger = logging.getLogger(__name__)


def hash_password(plaintext: str) -> str:
    """Return a bcrypt hash for *plaintext*. Use this once to set PASSWORD_HASH."""
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    """
    Constant-time bcrypt verification.
    Returns True if *plaintext* matches *hashed*.
    Exceptions (e.g. malformed hash) are caught and treated as failures.
    """
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Lockout tracker
# ---------------------------------------------------------------------------

@dataclass
class _AttemptRecord:
    count: int = 0
    locked_until: float = 0.0


class LockoutTracker:
    """
    Thread-safe tracker that enforces a lockout after N consecutive failures.

    *key* is typically an IP address or a username string — never the password.
    """

    def __init__(self, max_attempts: int, lockout_seconds: int) -> None:
        self._max = max_attempts
        self._lockout = lockout_seconds
        self._records: Dict[str, _AttemptRecord] = {}
        self._lock = Lock()

    def is_locked(self, key: str) -> bool:
        with self._lock:
            rec = self._records.get(key)
            if rec is None:
                return False
            if rec.locked_until and time.monotonic() < rec.locked_until:
                return True
            # Lockout expired — clear it
            if rec.locked_until and time.monotonic() >= rec.locked_until:
                self._records.pop(key, None)
            return False

    def record_failure(self, key: str) -> None:
        with self._lock:
            rec = self._records.setdefault(key, _AttemptRecord())
            rec.count += 1
            if rec.count >= self._max:
                rec.locked_until = time.monotonic() + self._lockout
                logger.warning(
                    "Client '%s' locked out for %ds after %d failed attempts.",
                    key,
                    self._lockout,
                    rec.count,
                )

    def record_success(self, key: str) -> None:
        with self._lock:
            self._records.pop(key, None)

    def seconds_remaining(self, key: str) -> float:
        with self._lock:
            rec = self._records.get(key)
            if rec is None:
                return 0.0
            remaining = rec.locked_until - time.monotonic()
            return max(remaining, 0.0)


# ---------------------------------------------------------------------------
# Authenticator (facade used by api.py and cli.py)
# ---------------------------------------------------------------------------

class Authenticator:
    """
    High-level auth facade.

    Usage::

        auth = Authenticator(config)
        result = auth.authenticate(password="...", client_key="127.0.0.1")
        if result.success:
            # proceed
    """

    def __init__(self, config: Config) -> None:
        self._hash = config.password_hash
        self._tracker = LockoutTracker(
            max_attempts=config.max_failed_attempts,
            lockout_seconds=config.lockout_seconds,
        )

    @dataclass
    class Result:
        success: bool
        locked_out: bool = False
        seconds_remaining: float = 0.0
        message: str = ""

    def authenticate(self, password: str, client_key: str = "default") -> "Authenticator.Result":
        if self._tracker.is_locked(client_key):
            secs = self._tracker.seconds_remaining(client_key)
            return self.Result(
                success=False,
                locked_out=True,
                seconds_remaining=secs,
                message=f"Too many failed attempts. Try again in {int(secs)}s.",
            )

        if verify_password(password, self._hash):
            self._tracker.record_success(client_key)
            logger.info("Successful authentication from '%s'.", client_key)
            return self.Result(success=True, message="Authenticated.")

        self._tracker.record_failure(client_key)
        logger.warning("Failed authentication attempt from '%s'.", client_key)
        return self.Result(success=False, message="Invalid password.")
