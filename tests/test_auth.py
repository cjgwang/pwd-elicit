"""
Tests for auth.py

Covers:
- correct password unlocks access
- wrong password is rejected
- lockout after repeated failures
- lockout clears on success
"""

import time

import pytest

from src.auth import Authenticator, hash_password, verify_password
from src.config import Config


# ---------------------------------------------------------------------------
# Unit: hash / verify
# ---------------------------------------------------------------------------

def test_hash_is_not_plaintext(test_password):
    hashed = hash_password(test_password)
    assert hashed != test_password


def test_verify_correct_password(test_password, test_hash):
    assert verify_password(test_password, test_hash) is True


def test_verify_wrong_password(test_hash):
    assert verify_password("wrong-password", test_hash) is False


def test_verify_empty_password(test_hash):
    assert verify_password("", test_hash) is False


def test_verify_malformed_hash():
    assert verify_password("anything", "not-a-valid-hash") is False


# ---------------------------------------------------------------------------
# Integration: Authenticator
# ---------------------------------------------------------------------------

@pytest.fixture()
def config(test_hash) -> Config:
    return Config(
        password_hash=test_hash,
        session_ttl_seconds=60,
        max_failed_attempts=3,
        lockout_seconds=10,
        model_name="distilgpt2",
        max_new_tokens=50,
        device="cpu",
        host="127.0.0.1",
        port=8000,
    )


@pytest.fixture()
def auth(config) -> Authenticator:
    return Authenticator(config)


def test_correct_password_succeeds(auth, test_password):
    result = auth.authenticate(password=test_password, client_key="test-client")
    assert result.success is True
    assert result.locked_out is False


def test_wrong_password_is_rejected(auth):
    result = auth.authenticate(password="bad-password", client_key="test-client-2")
    assert result.success is False
    assert result.locked_out is False


def test_lockout_after_repeated_failures(auth):
    key = "lockout-test-client"
    for _ in range(3):
        result = auth.authenticate(password="bad", client_key=key)
        assert result.success is False

    # 4th attempt should be locked out
    result = auth.authenticate(password="bad", client_key=key)
    assert result.locked_out is True
    assert result.success is False
    assert result.seconds_remaining > 0


def test_correct_password_clears_lockout_counter(auth, test_password):
    key = "clear-counter-client"
    # Two failures
    auth.authenticate(password="bad", client_key=key)
    auth.authenticate(password="bad", client_key=key)
    # Correct password — should succeed and reset counter
    result = auth.authenticate(password=test_password, client_key=key)
    assert result.success is True
    # Another failure should NOT immediately lock (counter was reset)
    result2 = auth.authenticate(password="bad", client_key=key)
    assert result2.locked_out is False


def test_different_clients_tracked_independently(auth):
    for i in range(3):
        auth.authenticate(password="bad", client_key="client-A")

    # client-B should not be locked
    result = auth.authenticate(password="bad", client_key="client-B")
    assert result.locked_out is False

    # client-A should be locked
    result = auth.authenticate(password="bad", client_key="client-A")
    assert result.locked_out is True
