"""
Tests for api.py

Uses TestClient from httpx (via starlette) with the model mocked out so
tests run without a GPU or downloaded weights.

Covers:
- unauthenticated requests do not reach the model
- correct password returns a session token
- wrong password returns 401
- locked-out client returns 429
- valid session allows chat
- expired/invalid token returns 401
- logout invalidates the session
"""

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.auth import Authenticator
from src.config import Config
from src.api import create_app
from src.session import SessionStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config(test_hash) -> Config:
    return Config(
        password_hash=test_hash,
        session_ttl_seconds=60,
        max_failed_attempts=3,
        lockout_seconds=300,
        model_name="distilgpt2",
        max_new_tokens=50,
        device="cpu",
        host="127.0.0.1",
        port=8000,
    )


@pytest.fixture()
def client(config):
    """
    TestClient with model loading and inference mocked so no actual
    HuggingFace model is required.
    """
    with (
        patch("src.api.load_model"),                        # skip model download
        patch("src.api.generate", return_value="mocked reply"),  # skip inference
        patch("src.api.is_loaded", return_value=True),
    ):
        app = create_app(config)
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login(client, password) -> dict:
    return client.post("/auth/login", json={"password": password})


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth endpoint tests
# ---------------------------------------------------------------------------

def test_login_correct_password(client, test_password):
    resp = login(client, test_password)
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["expires_in"] > 0


def test_login_wrong_password(client):
    resp = login(client, "wrong-password")
    assert resp.status_code == 401
    assert "Invalid" in resp.json()["detail"]


def test_login_lockout(client):
    for _ in range(3):
        login(client, "bad")

    resp = login(client, "bad")
    assert resp.status_code == 429
    assert "Too many" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------

def test_chat_without_token_is_rejected(client):
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 401


def test_chat_with_invalid_token_is_rejected(client):
    resp = client.post(
        "/chat",
        json={"message": "hello"},
        headers=auth_header("not-a-real-token"),
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Authenticated chat
# ---------------------------------------------------------------------------

def test_chat_after_login(client, test_password):
    token = login(client, test_password).json()["token"]
    resp = client.post(
        "/chat",
        json={"message": "hello"},
        headers=auth_header(token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "mocked reply"
    assert data["session_expires_in"] > 0


def test_model_not_called_without_auth(client):
    """Verify generate() is never called for unauthenticated requests."""
    with patch("src.api.generate") as mock_gen:
        client.post("/chat", json={"message": "hello"})
        mock_gen.assert_not_called()


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

def test_logout_invalidates_session(client, test_password):
    token = login(client, test_password).json()["token"]

    # Logout
    resp = client.post("/auth/logout", headers=auth_header(token))
    assert resp.status_code == 200

    # Further chat attempts should fail
    resp = client.post(
        "/chat",
        json={"message": "still here?"},
        headers=auth_header(token),
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Status endpoint (no auth required)
# ---------------------------------------------------------------------------

def test_status_endpoint(client):
    resp = client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["model_loaded"] is True
