## assistant-ui Integration Research (TeleClaude Web Frontend)

This document focuses on integrating the `assistant-ui` repository as TeleClaude's web frontend.

## What assistant-ui gives us

- A production-grade React chat UI layer (thread/composer/messages, streaming UX, keyboard/a11y).
- Integration paths for AI SDK and custom backends.
- A CLI (`create`/`init`) for fast scaffolding in Next.js projects.

## TeleClaude integration target

Use `assistant-ui` as the web client only. Keep TeleClaude daemon as backend authority.

- Frontend: Next.js + `assistant-ui`
- Backend for frontend (BFF): Next.js API routes
- Core backend: TeleClaude daemon (`/sessions`, `/messages`, `/ws`, MCP tools)

## Recommended architecture

### 1) Web frontend boundary

- `assistant-ui` components live in Next.js app.
- Browser never calls daemon internals directly.
- Next.js API routes proxy/translate to TeleClaude API and websocket.

### 2) Identity and metadata mapping

At BFF layer:

- Validate incoming auth token/session.
- Resolve person identity (email/telegram/whatsapp identifiers) against configured persons.
- Construct normalized metadata for every TeleClaude request:
  - `human_id`
  - `human_role`
  - `human_name` (optional)
  - `source_adapter=web`
  - `trusted=true|false`

Then pass that metadata into session create/message calls.

### 3) Session model mapping

assistant-ui thread != daemon process by default. We map explicitly:

- assistant-ui `threadId` -> TeleClaude `session_id`
- client-side thread state -> server-side authoritative session metadata
- stream output via daemon websocket (or SSE bridge) into assistant-ui message stream

### 4) Streaming

Two valid approaches:

- Preferred now: Next.js route bridges daemon websocket to frontend (single browser-friendly channel).
- Future: direct web adapter channel from daemon when stable.

## Migration plan (pragmatic)

1. Scaffold a Next.js shell with assistant-ui (`init` on existing web app or starter template).
2. Build a minimal BFF route for:
   - create/get session
   - send message
   - stream outputs
3. Add identity resolver middleware in BFF and inject normalized metadata.
4. Replace current web chat UI with assistant-ui thread/composer primitives.
5. Add role-aware UX controls (read-only/tool restrictions) from metadata.
6. Validate parity with Telegram/TUI for session behavior and observability.

## Non-goals

- Rewriting TeleClaude backend around assistant-ui.
- Storing user identity in local home-path token files.
- Making assistant-ui the source of truth for roles/persons.

## Risks and controls

- Protocol mismatch (assistant-ui runtime expectations vs daemon payloads):
  - control: strict translation layer in BFF + contract tests.
- Session drift:
  - control: treat daemon session state as authoritative.
- Identity leakage:
  - control: resolve/normalize at BFF once, never trust raw client claims downstream.

## What should exist next in this repo

- `docs/third-party/assistant-ui/` expanded with:
  - `integration.md` (end-to-end integration contract)
  - `thread-mapping.md` (assistant-ui thread <-> TeleClaude session mapping)
  - `streaming.md` (WS/SSE bridge details)
- `todos/person-identity-auth*/` updated to include web metadata injection at boundary.

## Sources

- https://www.assistant-ui.com/docs/getting-started
- https://www.assistant-ui.com/docs/installation
- https://www.assistant-ui.com/docs/cli
- https://www.assistant-ui.com/docs/runtimes/ai-sdk/use-assistant-hook
- https://github.com/assistant-ui/assistant-ui
- https://github.com/assistant-ui/assistant-ui-starter
  | ---------------- | ------------------------------------- | -------- |
  | PyJWT | Token creation and verification | >= 2.8 |
  | cryptography | Key generation (if asymmetric needed) | Optional |
  | email (stdlib) | SMTP magic-link delivery | Built-in |
  | smtplib (stdlib) | SMTP transport | Built-in |

### Token Module Pattern

```python
# teleclaude/auth/tokens.py
import jwt
import uuid
from datetime import datetime, timedelta, timezone

ALGORITHM = "HS256"

def create_magic_link_token(
    username: str, email: str, role: str,
    secret: str, ttl_minutes: int = 10,
    nonce: str | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": username,
        "email": email,
        "role": role,
        "purpose": "magic_link",
        "iss": "teleclaude",
        "aud": "teleclaude-auth",
        "iat": now,
        "exp": now + timedelta(minutes=ttl_minutes),
        "jti": str(uuid.uuid4()),
    }
    if nonce:
        claims["nonce"] = nonce
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def verify_magic_link_token(token: str, secrets: list[str]) -> dict:
    for secret in secrets:
        try:
            payload = jwt.decode(
                token, secret,
                algorithms=[ALGORITHM],
                issuer="teleclaude",
                audience="teleclaude-auth",
            )
            if payload.get("purpose") != "magic_link":
                raise ValueError("Wrong token purpose")
            return payload
        except jwt.InvalidSignatureError:
            continue
    raise jwt.InvalidSignatureError("No valid key found")


def create_session_token(
    username: str, email: str, role: str,
    secret: str, ttl_days: int = 7,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": username,
        "email": email,
        "role": role,
        "sid": str(uuid.uuid4()),
        "iss": "teleclaude",
        "aud": "teleclaude-web",
        "iat": now,
        "exp": now + timedelta(days=ttl_days),
    }, secret, algorithm=ALGORITHM)
```

### FastAPI Auth Endpoints Pattern

```python
# teleclaude/auth/routes.py
from fastapi import APIRouter, Response, Request, HTTPException, Query

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/start")
async def auth_start(email: str, request: Request, response: Response):
    person = resolve_person_by_email(email)
    if not person:
        raise HTTPException(404, "Unknown user")
    nonce = generate_nonce()
    token = create_magic_link_token(
        person.username, person.email, person.role,
        secret=get_signing_key(), nonce=nonce,
    )
    response.set_cookie("tc_nonce", nonce, httponly=True, max_age=900)
    await send_magic_link_email(person.email, token)
    return {"status": "sent"}


@router.get("/callback")
async def auth_callback(
    token: str = Query(...),
    request: Request, response: Response,
):
    nonce_cookie = request.cookies.get("tc_nonce")
    payload = verify_magic_link_token(token, get_verify_keys())
    if nonce_cookie and payload.get("nonce") != nonce_cookie:
        raise HTTPException(403, "Nonce mismatch")
    session_token = create_session_token(
        payload["sub"], payload["email"], payload["role"],
        secret=get_signing_key(),
    )
    response.set_cookie(
        "tc_session", session_token,
        httponly=True, secure=True, samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    response.delete_cookie("tc_nonce")
    return RedirectResponse("/")


@router.post("/logout")
async def auth_logout(response: Response):
    response.delete_cookie("tc_session")
    return {"status": "logged_out"}
```

### Middleware Pattern

```python
# teleclaude/auth/middleware.py
from starlette.middleware.base import BaseHTTPMiddleware

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # Skip auth for public routes
        if request.url.path.startswith("/auth/"):
            return await call_next(request)

        token = request.cookies.get("tc_session")
        if not token:
            return JSONResponse({"error": "Not authenticated"}, 401)

        try:
            payload = verify_session_token(token, get_verify_keys())
        except Exception:
            response = JSONResponse({"error": "Invalid session"}, 401)
            response.delete_cookie("tc_session")
            return response

        # Resolve authoritative role from config
        person = resolve_person_by_username(payload["sub"])
        if not person:
            return JSONResponse({"error": "Unknown user"}, 403)

        request.state.identity = IdentityContext(
            username=person.username,
            email=person.email,
            role=person.role,  # Config is authoritative
            sid=payload["sid"],
        )
        return await call_next(request)
```

### Email Delivery (stdlib SMTP)

No existing SMTP infrastructure in the codebase. Use Python stdlib:

```python
import smtplib
from email.mime.text import MIMEText

async def send_magic_link_email(to_email: str, token: str):
    callback_url = f"{config.base_url}/auth/callback?token={token}"
    msg = MIMEText(f"Click to log in: {callback_url}\n\nExpires in 10 minutes.")
    msg["Subject"] = "TeleClaude Login"
    msg["From"] = config.smtp.sender
    msg["To"] = to_email
    with smtplib.SMTP(config.smtp.host, config.smtp.port) as server:
        if config.smtp.use_tls:
            server.starttls()
        if config.smtp.username:
            server.login(config.smtp.username, config.smtp.password)
        server.send_message(msg)
```

---

## Q7: Role Claim Propagation to Tool Gating and Spawned Sessions

### Propagation Chain

```
Magic Link Token          Session Cookie           Request State
  role: "admin"    --->     role: "admin"    --->    identity.role
                                                         |
                                    +--------------------+--------------------+
                                    |                    |                    |
                               API handlers        MCP wrapper         Tool filtering
                                    |                    |                    |
                               Web views         Child sessions       Blocked tools
```

### Tool Gating Integration

The existing MCP wrapper already filters tools based on agent role. Extend this to
include human role:

```python
# Effective permissions = intersection of agent_role and human_role
def get_allowed_tools(agent_role: str, human_role: str) -> set[str]:
    agent_tools = AGENT_ROLE_TOOLS[agent_role]
    human_tools = HUMAN_ROLE_TOOLS[human_role]
    return agent_tools & human_tools
```

### Role Hierarchy

| Role          | Tool Access                                     | View Access      |
| ------------- | ----------------------------------------------- | ---------------- |
| `admin`       | All tools                                       | All views        |
| `member`      | Operational tools (no destructive/system admin) | All views        |
| `contributor` | Scoped tools (read + limited write)             | Scoped views     |
| `newcomer`    | Minimal guided tools                            | Onboarding views |

### Session Inheritance

When a human-initiated action spawns a child session:

1. Parent session's `IdentityContext` is serialized into session metadata.
2. Child session reads inherited identity from metadata.
3. MCP wrapper enforces the inherited human role on tool filtering.
4. Audit log records both the human identity and the spawning session chain.

```python
# On session creation
session_metadata = {
    "human_identity": {
        "username": request.state.identity.username,
        "email": request.state.identity.email,
        "role": request.state.identity.role,
        "origin_sid": request.state.identity.sid,
    }
}
```

### Telegram Entry Point

Telegram users are identified by `telegram_user_id` mapped to a person in config.
No cookie flow needed — identity is resolved directly from the Telegram adapter.

---

## Architecture Decision: Recommended Approach

### Token Format: JWT (HS256)

- **Library**: PyJWT >= 2.8
- **Algorithm**: HS256 (symmetric, hardcoded — no algorithm header trust)
- **Why not PASETO**: Overkill for single-service symmetric use; JWT ecosystem is
  stronger in Python

### Replay Mitigation: Short TTL + Nonce Binding

- **Magic-link TTL**: 10 minutes
- **Session cookie TTL**: 7 days (configurable)
- **Nonce binding**: Pre-auth cookie paired with token claim
- **Upgrade path**: In-memory JTI tracking, then SQLite consumed-token table

### Key Management: Dual-Key Overlap Rotation

- **Signing key**: Single active key from config
- **Verification keys**: Active + previous keys for overlap window
- **Emergency revocation**: Drop all previous keys, force global re-auth
- **Storage**: Keys in config (not hardcoded), rotated manually or via procedure

### Identity Source of Truth: Config

- Config is authoritative for person existence and role.
- Token carries claims as a performance cache, not as authorization source.
- Middleware always re-validates against config.

---

## Migration Risks

| Risk                                  | Impact                                                          | Mitigation                                              |
| ------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------- |
| No SMTP config exists                 | Auth flow blocked until SMTP is configured                      | Provide fallback: log magic link to console in dev mode |
| Config schema extension               | Breaking change if `email`/`role` become required               | Make fields optional with defaults during migration     |
| Cookie conflicts with existing routes | Unexpected auth failures                                        | Use unique cookie name (`tc_session`), explicit path    |
| Key in config is a secret             | Accidental commit to git                                        | Use env var override, document in `.env.example`        |
| Session TTL vs config role changes    | Stale role in token (not in practice — middleware reads config) | Document that config role is authoritative              |

---

## Sources

- [JWT vs PASETO: New Era of Token-Based Authentication](https://permify.co/post/jwt-paseto/) — Security comparison
- [Why PASETO is Better Than JWT](https://dev.to/techschoolguru/why-paseto-is-better-than-jwt-for-token-based-authentication-1b0c) — Algorithm confusion attacks, version breakdown
- [PySETO Usage Examples](https://pyseto.readthedocs.io/en/latest/paseto_usage.html) — Python PASETO v4 implementation
- [Magic Link Security: Best Practices & Advanced Techniques](https://guptadeepak.com/mastering-magic-link-security-a-deep-dive-for-developers/) — Threat model, attack vectors, mitigations
- [Email Magic Links - Clerk](https://clerk.com/blog/magic-links) — Magic link overview and security model
- [FastAPI Passwordless Magic Link & OTP - Scalekit](https://www.scalekit.com/blog/fastapi-passwordless-magic-link-otp-implementation) — FastAPI implementation patterns
- [JWT and Cookie Auth in FastAPI](https://retz.dev/blog/jwt-and-cookie-auth-in-fastapi/) — Cookie auth patterns
- [JWTs in Microservices: Key Rotation and Session Invalidation](https://techblogsbypallavi.medium.com/jwts-in-microservices-how-to-rotate-keys-and-invalidate-sessions-cleanly-db30c1110fd7) — Key rotation strategies
- [The Hidden Power of JTI](https://elsyarifx.medium.com/the-hidden-power-of-jti-how-a-single-claim-can-stop-token-replay-attacks-0255fbcf6b9b) — JTI claim for replay prevention
- [PyJWT Documentation](https://pyjwt.readthedocs.io/en/latest/usage.html) — Python JWT library
- [PyJWT vs python-jose](https://stackshare.io/stackups/pypi-pyjwt-vs-pypi-python-jose) — Library comparison
- [Stateless Sessions & JWT-Only Mode - better-auth](https://deepwiki.com/better-auth/better-auth/11.6-stateless-sessions-and-jwt-only-mode) — Stateless session patterns
- [The Magic Link Vulnerability - Dfns](https://www.dfns.co/article/the-magic-link-vulnerability) — Redirect URL manipulation attack
- [RFC 7519 - JSON Web Token](https://datatracker.ietf.org/doc/html/rfc7519) — JWT specification
