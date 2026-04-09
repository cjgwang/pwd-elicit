"""
Shared fixtures for pytest.

The PASSWORD_HASH env var is set here so tests never need a real .env file.
"""

import os

import bcrypt
import pytest

# Use a known test password and pre-hash it once per session
TEST_PASSWORD = "correct-horse-battery-staple"
TEST_HASH = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt()).decode()

# Patch env before any config import
os.environ.setdefault("PASSWORD_HASH", TEST_HASH)
os.environ.setdefault("SESSION_TTL_SECONDS", "60")
os.environ.setdefault("MAX_FAILED_ATTEMPTS", "3")
os.environ.setdefault("LOCKOUT_SECONDS", "10")


@pytest.fixture()
def test_password() -> str:
    return TEST_PASSWORD


@pytest.fixture()
def test_hash() -> str:
    return TEST_HASH
