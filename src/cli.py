"""
CLI interface for the password-locked LLM.

Usage
-----
# Set a new password hash (run once):
    python -m src.cli set-password

# Start an interactive chat session:
    python -m src.cli chat

# Run the FastAPI server:
    python -m src.cli serve
"""

import getpass
import sys
import textwrap

import click

from .auth import Authenticator, hash_password
from .config import get_config
from .model import generate, load_model
from .session import SessionStore


@click.group()
def cli() -> None:
    """Password-locked LLM — CLI interface."""


# ---------------------------------------------------------------------------
# set-password
# ---------------------------------------------------------------------------

@cli.command("set-password")
def set_password() -> None:
    """
    Hash a new password and print the value to put in PASSWORD_HASH.

    The hash is printed to stdout so you can pipe it into your .env file:

        python -m src.cli set-password >> .env
    """
    password = getpass.getpass("Enter new password: ")
    confirm  = getpass.getpass("Confirm password:   ")
    if password != confirm:
        click.echo("Passwords do not match.", err=True)
        sys.exit(1)
    if not password:
        click.echo("Password cannot be empty.", err=True)
        sys.exit(1)

    hashed = hash_password(password)
    click.echo(f"\nAdd this line to your .env file:\n\nPASSWORD_HASH={hashed}\n")


# ---------------------------------------------------------------------------
# chat  (local, interactive)
# ---------------------------------------------------------------------------

@cli.command("chat")
@click.option("--model", default=None, help="Override MODEL_NAME from config.")
@click.option("--session-ttl", default=None, type=int, help="Session TTL in seconds.")
def chat(model: str | None, session_ttl: int | None) -> None:
    """
    Interactive chat after password authentication.

    Authentication is checked before the model is called. A simple
    in-process session tracks conversation history and expires after TTL.
    """
    try:
        config = get_config()
    except KeyError as exc:
        click.echo(
            f"Configuration error: {exc}\n"
            "Have you set PASSWORD_HASH in .env?",
            err=True,
        )
        sys.exit(1)

    if model:
        config.model_name = model
    if session_ttl:
        config.session_ttl_seconds = session_ttl

    auth  = Authenticator(config)
    store = SessionStore(ttl_seconds=config.session_ttl_seconds)

    click.echo("Password-Locked LLM  (type 'exit' or 'quit' to leave, 'logout' to re-authenticate)\n")

    # --- Authentication loop ---
    session = None
    client_key = "cli"

    while session is None:
        try:
            password = getpass.getpass("Password: ")
        except (KeyboardInterrupt, EOFError):
            click.echo("\nAborted.")
            sys.exit(0)

        result = auth.authenticate(password=password, client_key=client_key)

        if result.locked_out:
            click.echo(result.message, err=True)
            sys.exit(1)

        if result.success:
            session = store.create()
            click.echo(
                f"Authenticated. Session expires in {config.session_ttl_seconds}s "
                f"of inactivity.\n"
            )
        else:
            click.echo("Invalid password. Try again.")

    # --- Load model ---
    click.echo(f"Loading model '{config.model_name}'… (this may take a moment)")
    try:
        load_model(config.model_name, device=config.device)
    except RuntimeError as exc:
        click.echo(f"Model load error: {exc}", err=True)
        sys.exit(1)
    click.echo("Model ready. Start chatting!\n")

    # --- Chat loop ---
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            click.echo("\nGoodbye.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            click.echo("Goodbye.")
            break

        if user_input.lower() == "logout":
            store.invalidate(session.token)
            click.echo("Logged out.\n")
            # Re-authenticate
            session = None
            while session is None:
                try:
                    password = getpass.getpass("Password: ")
                except (KeyboardInterrupt, EOFError):
                    click.echo("\nAborted.")
                    sys.exit(0)
                result = auth.authenticate(password=password, client_key=client_key)
                if result.locked_out:
                    click.echo(result.message, err=True)
                    sys.exit(1)
                if result.success:
                    session = store.create()
                    click.echo("Authenticated.\n")
                else:
                    click.echo("Invalid password. Try again.")
            continue

        # Check session hasn't expired
        active = store.get(session.token)
        if active is None:
            click.echo("Session expired. Please log in again.")
            sys.exit(1)

        history = [{"role": m.role, "content": m.content} for m in active.history]

        try:
            reply = generate(
                prompt=user_input,
                history=history,
                max_new_tokens=config.max_new_tokens,
            )
        except RuntimeError as exc:
            click.echo(f"Model error: {exc}", err=True)
            break

        active.append("user", user_input)
        active.append("assistant", reply)

        wrapped = textwrap.fill(reply, width=80)
        click.echo(f"\nAssistant: {wrapped}\n")


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

@cli.command("serve")
@click.option("--host", default=None, help="Override HOST from config.")
@click.option("--port", default=None, type=int, help="Override PORT from config.")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev mode).")
def serve(host: str | None, port: int | None, reload: bool) -> None:
    """Start the FastAPI server."""
    try:
        import uvicorn
    except ImportError:
        click.echo("uvicorn is not installed. Run: pip install uvicorn", err=True)
        sys.exit(1)

    try:
        config = get_config()
    except KeyError as exc:
        click.echo(f"Configuration error: {exc}", err=True)
        sys.exit(1)

    uvicorn.run(
        "src.api:app",
        host=host or config.host,
        port=port or config.port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    cli()
