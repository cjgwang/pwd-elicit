# Password-Locked LLM

A production-leaning demo where an LLM only responds after a correct password is provided. Authentication is implemented entirely at the application layer — no fine-tuned backdoors, no plaintext secrets.

## Architecture

```
src/
├── config.py   — loads settings from .env (no secrets stored in code)
├── auth.py     — bcrypt password verification + per-client lockout tracker
├── session.py  — in-memory session store with TTL-based expiry
├── model.py    — HuggingFace causal LM wrapper (isolated from auth concerns)
├── api.py      — FastAPI app (login, logout, chat endpoints)
└── cli.py      — interactive CLI chat + set-password + serve commands
tests/
├── test_auth.py
├── test_session.py
└── test_api.py
```

**Key guarantee:** the `generate()` call in `model.py` is never reached unless a valid session token is present. The FastAPI dependency `get_session` enforces this at the framework level before the endpoint handler runs.

---

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> **No GPU?** The default model (`distilgpt2`) runs fine on CPU. Change `MODEL_NAME` in `.env` for a larger model.

### 2. Create your `.env` file

```bash
cp .env.example .env
```

### 3. Set the password hash

This hashes your chosen password with bcrypt and prints the line to add to `.env`. The plaintext password is never written anywhere.

```bash
python -m src.cli set-password
# Enter new password: ••••••••
# Confirm password:   ••••••••
#
# Add this line to your .env file:
#
# PASSWORD_HASH=$2b$12$...
```

Copy the `PASSWORD_HASH=...` line into `.env`.

---

## Usage

### CLI (interactive chat)

```bash
python -m src.cli chat
```

```
Password-Locked LLM  (type 'exit' or 'quit' to leave, 'logout' to re-authenticate)

Password: ••••••••
Authenticated. Session expires in 3600s of inactivity.

Loading model 'distilgpt2'… (this may take a moment)
Model ready. Start chatting!

You: What is the capital of France?
Assistant: The capital of France is Paris…

You: logout
Logged out.

Password: ••••••••
```

### API server

```bash
python -m src.cli serve
# or directly:
uvicorn src.api:app --host 127.0.0.1 --port 8000
```

#### 1. Unlock the session — exchange password for a token

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "your-password"}' | python -m json.tool
```

```json
{
  "token": "abc123...",
  "expires_in": 3600
}
```

#### 2. Chat after unlock

```bash
TOKEN="abc123..."

curl -s -X POST http://localhost:8000/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Explain bcrypt in one sentence."}' | python -m json.tool
```

```json
{
  "reply": "bcrypt is a password hashing function…",
  "session_expires_in": 3598.4
}
```

#### 3. Log out / expire the session

```bash
curl -s -X POST http://localhost:8000/auth/logout \
  -H "Authorization: Bearer $TOKEN"
```

```json
{"detail": "Logged out."}
```

Subsequent requests with the same token return `401 Unauthorized`.

#### 4. Unauthenticated request (safe rejection — model is not called)

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
```

```json
{"detail": "Authentication required."}
```

#### 5. Health check (no auth)

```bash
curl http://localhost:8000/status
```

```json
{
  "status": "ok",
  "model_loaded": true,
  "model_name": "distilgpt2",
  "active_sessions": 1
}
```

---

## Security design decisions

| Concern | Decision |
|---|---|
| Password storage | bcrypt hash in `PASSWORD_HASH` env var; never plaintext |
| Password logging | Passwords are never passed to the logger |
| Model gate | `generate()` is only reachable after `get_session()` dependency passes |
| Session tokens | 32-byte URL-safe random (256-bit entropy), opaque to the client |
| Rate limiting | Per-client-IP lockout after N failures; configurable TTL |
| Session expiry | Idle TTL reset on each request; explicit logout supported |
| No fine-tuning | Model has no "knowledge" of the password; it's a plain inference call |

---

## Configuration reference

| Variable | Default | Description |
|---|---|---|
| `PASSWORD_HASH` | *(required)* | bcrypt hash of the access password |
| `SESSION_TTL_SECONDS` | `3600` | Idle timeout before session expires |
| `MAX_FAILED_ATTEMPTS` | `5` | Failures before lockout |
| `LOCKOUT_SECONDS` | `300` | Duration of lockout |
| `MODEL_NAME` | `distilgpt2` | HuggingFace model ID |
| `MAX_NEW_TOKENS` | `200` | Max tokens generated per reply |
| `MODEL_DEVICE` | `cpu` | `cpu` or `cuda` |
| `HOST` | `127.0.0.1` | API bind address |
| `PORT` | `8000` | API port |

---

## Running tests

```bash
pytest -v
```

Tests mock the model so no GPU or model download is required. Auth and session tests run against real bcrypt and in-memory stores.

```
tests/test_auth.py::test_correct_password_succeeds          PASSED
tests/test_auth.py::test_wrong_password_is_rejected         PASSED
tests/test_auth.py::test_lockout_after_repeated_failures    PASSED
tests/test_session.py::test_session_expiry                  PASSED
tests/test_api.py::test_chat_without_token_is_rejected      PASSED
tests/test_api.py::test_model_not_called_without_auth       PASSED
...
```

---

## Extending

- **Multi-user:** replace the single `PASSWORD_HASH` with a user table and look up per-username hashes.
- **Persistent sessions:** swap `SessionStore`'s dict for Redis with `SET … EX ttl`.
- **Streaming:** add a `/chat/stream` endpoint using `StreamingResponse` and `model.py`'s pipeline with `streamer=`.
- **Different models:** set `MODEL_NAME` to any HuggingFace causal LM (e.g. `meta-llama/Llama-3.2-1B`).
