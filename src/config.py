"""
Configuration loader.

Reads settings from environment variables (populated from .env via python-dotenv).
No secrets are stored here — only references to where they live.
"""

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Password hash (bcrypt) stored as env var, never plaintext
    password_hash: str = field(
        default_factory=lambda: os.environ["PASSWORD_HASH"]
    )

    # Session settings
    session_ttl_seconds: int = field(
        default_factory=lambda: int(os.getenv("SESSION_TTL_SECONDS", "3600"))
    )

    # Lockout settings
    max_failed_attempts: int = field(
        default_factory=lambda: int(os.getenv("MAX_FAILED_ATTEMPTS", "5"))
    )
    lockout_seconds: int = field(
        default_factory=lambda: int(os.getenv("LOCKOUT_SECONDS", "300"))
    )

    # Model settings
    model_name: str = field(
        default_factory=lambda: os.getenv("MODEL_NAME", "distilgpt2")
    )
    max_new_tokens: int = field(
        default_factory=lambda: int(os.getenv("MAX_NEW_TOKENS", "200"))
    )
    device: str = field(
        default_factory=lambda: os.getenv("MODEL_DEVICE", "cpu")
    )

    # API settings
    host: str = field(default_factory=lambda: os.getenv("HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))


def get_config() -> Config:
    """Return a Config instance, raising KeyError if PASSWORD_HASH is missing."""
    return Config()
