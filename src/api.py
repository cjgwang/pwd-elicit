"""
FastAPI application.

Endpoints
---------
POST /auth/login          — exchange password for a session token
POST /auth/logout         — invalidate a session token
POST /chat                — send a message (requires valid session token)
GET  /status              — health check (no auth required)

The session token is passed in the Authorization header:
    Authorization: Bearer <token>
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .auth import Authenticator
from .config import Config, get_config
from .model import generate, is_loaded, load_model
from .session import Session, SessionStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    token: str
    expires_in: int   # seconds


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)


class ChatResponse(BaseModel):
    reply: str
    session_expires_in: float


class StatusResponse(BaseModel):
    status: str
    model_loaded: bool
    model_name: str | None
    active_sessions: int


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or get_config()
    auth = Authenticator(cfg)
    store = SessionStore(ttl_seconds=cfg.session_ttl_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Load the model once at startup
        load_model(cfg.model_name, device=cfg.device)
        yield
        # (cleanup if needed)

    app = FastAPI(
        title="Password-Locked LLM",
        description="Chat with an LLM after authenticating with a password.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # -----------------------------------------------------------------------
    # Dependency: resolve + validate session from Bearer token
    # -----------------------------------------------------------------------

    def get_session(
        authorization: str | None = Header(default=None),
    ) -> Session:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization.removeprefix("Bearer ").strip()
        session = store.get(token)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session not found or expired. Please log in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return session

    # -----------------------------------------------------------------------
    # Routes
    # -----------------------------------------------------------------------

    @app.get("/status", response_model=StatusResponse)
    async def status_endpoint() -> StatusResponse:
        from .model import current_model
        return StatusResponse(
            status="ok",
            model_loaded=is_loaded(),
            model_name=current_model(),
            active_sessions=store.active_count(),
        )

    @app.post("/auth/login", response_model=LoginResponse)
    async def login(body: LoginRequest, request: Request) -> LoginResponse:
        client_key = request.client.host if request.client else "unknown"
        result = auth.authenticate(password=body.password, client_key=client_key)

        if result.locked_out:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=result.message,
            )
        if not result.success:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=result.message,
            )

        session = store.create()
        return LoginResponse(
            token=session.token,
            expires_in=cfg.session_ttl_seconds,
        )

    @app.post("/auth/logout")
    async def logout(session: Session = Depends(get_session)) -> JSONResponse:
        store.invalidate(session.token)
        return JSONResponse({"detail": "Logged out."})

    @app.post("/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest,
        session: Session = Depends(get_session),
    ) -> ChatResponse:
        # Build history for context (convert Message objects to dicts)
        history = [
            {"role": m.role, "content": m.content}
            for m in session.history
        ]

        reply = generate(
            prompt=body.message,
            history=history,
            max_new_tokens=cfg.max_new_tokens,
        )

        # Persist to session history
        session.append("user", body.message)
        session.append("assistant", reply)

        return ChatResponse(
            reply=reply,
            session_expires_in=session.seconds_remaining(),
        )

    return app


# Allow running directly with `uvicorn src.api:app`
app = create_app()
