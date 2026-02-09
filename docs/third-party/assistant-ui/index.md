# Stateless Email Magic-Link Authentication Without Verification DB

Research brief for the `person-identity-auth` work item.

## Executive Summary

Stateless magic-link auth using signed tokens (JWT or PASETO) with session cookies is
a well-established pattern that is **secure enough for small trusted deployments**
when implemented with short TTLs, proper signature verification, and explicit replay
limitations. The main tradeoff is accepting that without server-side state, true
one-time-use token invalidation is not guaranteed — mitigated by short expiry windows
and optional nonce binding.

**Recommendation:** Use **PyJWT with HS256** for magic-link tokens and session cookies.
JWT wins over PASETO on ecosystem maturity, library support, and simplicity for this
use case. Reserve PASETO as a future upgrade path if algorithm confusion becomes a
concern (unlikely in a single-service deployment).

---

## Q1: Is DB-less Magic-Link Secure Enough for Small Trusted Deployment?

**Yes, with explicit constraints.**

### Threat Model

| Threat                                | Severity | Stateless Mitigation                                   | Residual Risk          |
| ------------------------------------- | -------- | ------------------------------------------------------ | ---------------------- |
| Token interception (network)          | High     | HTTPS-only delivery, short TTL (10-15 min)             | Low if TLS enforced    |
| Email account compromise              | High     | Out of scope — delegates to email provider security    | Accepted               |
| Token replay (reuse before expiry)    | Medium   | Short TTL + optional nonce binding                     | Low for small user set |
| Redirect URL manipulation             | High     | Hardcoded callback URL, no user-supplied redirect      | Eliminated             |
| Session fixation                      | Medium   | Generate fresh `sid` on each login                     | Eliminated             |
| Algorithm confusion (JWT `alg: none`) | Critical | Hardcode algorithm in verification, never trust header | Eliminated             |
| Key compromise                        | Critical | Key rotation procedure, forced re-auth                 | Mitigated              |
| Clickjacking on magic link            | Low      | X-Frame-Options: DENY, CSP frame-ancestors             | Eliminated             |

### Why It Works for This Profile

- **Small user set** (< 10 people): replay window affects few accounts.
- **Trusted users**: social trust reduces insider attack surface.
- **Local/private deployment**: network exposure is limited.
- **Config-driven identity**: person records live in `config.yml`, not a user registration DB.

### Explicit Limitations to Document

1. A magic-link token can be used more than once within its TTL window.
2. Token revocation requires key rotation (affects all sessions) or waiting for expiry.
3. If email is compromised, attacker gets access until token expires.

---

## Q2: JWT vs PASETO Tradeoffs

### Comparison

| Property            | JWT (RFC 7519)                                        | PASETO                                           |
| ------------------- | ----------------------------------------------------- | ------------------------------------------------ |
| Algorithm selection | Developer chooses (risk of misconfiguration)          | Version determines algorithm (secure by default) |
| `alg: none` attack  | Possible if library allows                            | Impossible (no algorithm header)                 |
| Algorithm confusion | Possible (RS256/HS256 swap)                           | Impossible (version = algorithm)                 |
| Encryption support  | Via JWE (separate spec)                               | Built-in (`local` purpose = AEAD)                |
| Python libraries    | PyJWT (mature, minimal deps), python-jose (full JOSE) | pyseto (v1-v4, actively maintained), pypaseto    |
| Ecosystem maturity  | Dominant standard, universal support                  | Growing but niche                                |
| Performance         | ~0.5ms generation                                     | ~2.4ms generation                                |
| Debugging tools     | jwt.io, widespread tooling                            | Limited                                          |

### PASETO Version Algorithms

| Version      | Local (symmetric)                | Public (asymmetric) |
| ------------ | -------------------------------- | ------------------- |
| v1 (legacy)  | AES-256-CTR + HMAC-SHA384        | RSA-PSS + SHA384    |
| v2           | XChaCha20-Poly1305               | Ed25519             |
| v3           | AES-256-CTR + HMAC-SHA384 (NIST) | ECDSA P-384         |
| v4 (current) | XChaCha20-Poly1305 + BLAKE2b     | Ed25519             |

### Recommendation

**Use JWT (PyJWT + HS256)** for this project:

- Single service, single signing key — algorithm confusion is not a real risk.
- Hardcode `algorithm="HS256"` in both sign and verify — eliminates the `alg: none`
  and algorithm confusion vectors entirely.
- PyJWT is a zero-additional-dependency choice (already common in Python ecosystems).
- PASETO adds complexity without material security gain for symmetric single-service use.

**If asymmetric signing is needed later** (e.g., third-party token verification), consider
upgrading to Ed25519 via PyJWT (`algorithm="EdDSA"`) or switching to PASETO v4.public.

---

## Q3: Replay Mitigation Without Persistent Token Store

### The Core Problem

Without server-side state, you cannot track which tokens have been consumed. A valid,
unexpired magic-link token can be used multiple times within its TTL.

### Mitigation Strategies (No DB Required)

#### Strategy 1: Short TTL (Primary)

- Set magic-link TTL to **10 minutes** (or less).
- The replay window is bounded by TTL — acceptable for small trusted deployments.
- Implementation: `exp` claim in JWT, verified on every request.

#### Strategy 2: Nonce Binding via Pre-Auth Cookie

- On `POST /auth/start`, set a short-lived HttpOnly cookie with a random `nonce`.
- Embed the same `nonce` in the magic-link token's claims.
- On `GET /auth/callback`, verify `nonce` in token matches `nonce` in cookie.
- **Effect**: token is bound to the browser that initiated the login request.
  A different browser/device cannot replay the link.
- **Limitation**: same-browser replay is still possible within TTL.

#### Strategy 3: In-Memory JTI Tracking (Optional, Lightweight)

- Include a `jti` (JWT ID) claim with a UUID in each magic-link token.
- Maintain an in-memory set of consumed `jti` values with TTL-based expiry.
- Reject tokens whose `jti` is already in the set.
- **Tradeoff**: state is lost on daemon restart (acceptable — tokens are short-lived).
- **Implementation**: Python `dict` with timestamp cleanup, or `cachetools.TTLCache`.
- This is NOT a database — it's a volatile cache that self-cleans.

#### Strategy 4: One-Time Use via Token Hash in SQLite (Upgrade Path)

- If replay becomes a real concern, store consumed token hashes in the existing
  `teleclaude.db` SQLite — no new database needed.
- Query: `SELECT 1 FROM consumed_tokens WHERE hash = ? AND expires_at > NOW()`.
- Cleanup: periodic DELETE of expired entries.

### Recommended Approach

**Start with Strategy 1 + 2** (short TTL + nonce binding). Add Strategy 3 (in-memory
JTI) if replay is observed or becomes a concern. Strategy 4 is the upgrade path that
stays within the single-database policy.

---

## Q4: Session Cookie Claims and Validation

### Cookie Token Claims

```json
{
  "sub": "username",
  "email": "user@example.com",
  "role": "admin",
  "sid": "uuid-session-id",
  "iss": "teleclaude",
  "aud": "teleclaude-web",
  "iat": 1707500000,
  "exp": 1708104800
}
```

### Claim Purposes

| Claim   | Purpose                        | Validation                                 |
| ------- | ------------------------------ | ------------------------------------------ |
| `sub`   | Identity resolution            | Must match a person in config              |
| `email` | Identity confirmation          | Must match person's email in config        |
| `role`  | Authorization context          | Must be a valid role enum value            |
| `sid`   | Audit trail / session tracking | UUID, logged for observability             |
| `iss`   | Issuer verification            | Must equal `"teleclaude"`                  |
| `aud`   | Audience verification          | Must equal expected audience               |
| `iat`   | Token freshness                | Informational, used for rotation detection |
| `exp`   | Expiry enforcement             | Reject if current time > exp               |

### Cookie Configuration

```python
response.set_cookie(
    key="tc_session",
    value=token,
    httponly=True,
    secure=True,         # Set False for local HTTP dev
    samesite="lax",
    path="/",
    max_age=60 * 60 * 24 * 7,  # 7 days default
)
```

### Validation Flow (Middleware)

1. Extract `tc_session` cookie from request.
2. Decode and verify signature using server secret.
3. Verify `exp` (reject expired), `iss`, `aud`.
4. Resolve `sub` against config — reject if person no longer exists.
5. Compare `role` in token against current config role — use **config role** as
   authoritative (handles role changes between token issuance and request).
6. Attach normalized `IdentityContext(username, email, role)` to request state.

### Re-validation on Config Change

When config is reloaded and a person's role changes, active session cookies still carry
the old role. The middleware should **always read the authoritative role from config**,
using the token's `sub` for lookup. The token's `role` claim serves as a cache hint and
audit record, not as the authorization source.

---

## Q5: Key Rotation and Forced Re-Auth Strategy

### Key Rotation Procedure

#### Dual-Key Overlap Window

1. Generate new signing key (`key_v2`).
2. Update config to sign new tokens with `key_v2`.
3. Keep `key_v1` in a verification-only key list.
4. Verify incoming tokens against **all active keys** (try `key_v2` first, fall back
   to `key_v1`).
5. After overlap period (>= longest session TTL), remove `key_v1`.

#### Implementation

```python
SIGNING_KEY = config.auth.current_key       # Used for new tokens
VERIFY_KEYS = [config.auth.current_key] + config.auth.previous_keys  # Ordered

def verify_token(token: str) -> dict:
    for key in VERIFY_KEYS:
        try:
            return jwt.decode(token, key, algorithms=["HS256"], ...)
        except jwt.InvalidSignatureError:
            continue
    raise AuthenticationError("Invalid token signature")
```

#### Key ID (`kid`) Header (Optional)

- Include a `kid` in the JWT header to identify which key signed the token.
- Allows direct key lookup instead of iterating all keys.
- Adds a few bytes of overhead but improves verification performance with many keys.

### Forced Re-Auth Strategy

| Trigger               | Action                                                              |
| --------------------- | ------------------------------------------------------------------- |
| Key compromise        | Remove compromised key from verify list immediately                 |
| Role change           | Middleware already reads config role — no token invalidation needed |
| User removal          | Middleware rejects unknown `sub` — immediate lockout                |
| Explicit logout       | Clear cookie via `POST /auth/logout`                                |
| Global forced re-auth | Remove all previous keys, keep only new key                         |

### Emergency Key Revocation

1. Generate new key.
2. Set `VERIFY_KEYS = [new_key]` (no previous keys).
3. All existing tokens become invalid immediately.
4. All users must re-authenticate.

---

## Q6: FastAPI/Python Implementation Patterns

### Library Choice

| Library          | Use For                               | Version  |
| ---------------- | ------------------------------------- | -------- |
| PyJWT            | Token creation and verification       | >= 2.8   |
| cryptography     | Key generation (if asymmetric needed) | Optional |
| email (stdlib)   | SMTP magic-link delivery              | Built-in |
| smtplib (stdlib) | SMTP transport                        | Built-in |

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
