"""
Tests for session.py

Covers:
- session creation and retrieval
- session expiry
- explicit invalidation (logout)
- history accumulation
- multiple independent sessions
"""

import time

import pytest

from src.session import SessionStore


@pytest.fixture()
def store() -> SessionStore:
    return SessionStore(ttl_seconds=2)  # short TTL for expiry tests


def test_create_and_retrieve(store):
    session = store.create()
    retrieved = store.get(session.token)
    assert retrieved is not None
    assert retrieved.token == session.token


def test_unknown_token_returns_none(store):
    assert store.get("nonexistent-token") is None


def test_session_expiry(store):
    session = store.create()
    token = session.token

    # Should be valid immediately
    assert store.get(token) is not None

    # Wait for TTL to elapse
    time.sleep(2.1)
    assert store.get(token) is None


def test_touch_extends_session(store):
    """Accessing a session (get) touches it, resetting the idle timer."""
    session = store.create()
    token = session.token

    time.sleep(1.2)
    # Still alive — get() doesn't touch; touch via session.touch()
    active = store.get(token)
    assert active is not None
    active.touch()  # explicitly reset the idle timer

    time.sleep(1.2)
    # Should still be alive because we touched it
    assert store.get(token) is not None


def test_explicit_invalidation(store):
    session = store.create()
    token = session.token
    result = store.invalidate(token)
    assert result is True
    assert store.get(token) is None


def test_invalidate_nonexistent_returns_false(store):
    assert store.invalidate("ghost-token") is False


def test_history_accumulation(store):
    session = store.create()
    session.append("user", "hello")
    session.append("assistant", "hi there")

    active = store.get(session.token)
    assert active is not None
    assert len(active.history) == 2
    assert active.history[0].role == "user"
    assert active.history[1].role == "assistant"


def test_multiple_sessions_are_independent(store):
    s1 = store.create()
    s2 = store.create()
    assert s1.token != s2.token

    store.invalidate(s1.token)
    assert store.get(s1.token) is None
    assert store.get(s2.token) is not None


def test_active_count(store):
    assert store.active_count() == 0
    s1 = store.create()
    s2 = store.create()
    assert store.active_count() == 2
    store.invalidate(s1.token)
    assert store.active_count() == 1


def test_purge_expired(store):
    s = store.create()
    assert store.active_count() == 1
    time.sleep(2.1)
    removed = store.purge_expired()
    assert removed == 1
    assert store.active_count() == 0
