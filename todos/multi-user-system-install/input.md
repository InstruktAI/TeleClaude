# Multi-User System-Wide Installation

## Origin

Conversation during doc-access-control review (2026-02-18). While discussing the role system (`public`, `member`, `admin`), we realized the current single-user install model is a dead end for shared machines. The role system we built is the right foundation — but the deployment model needs to change to actually serve multiple people.

## The Vision

TeleClaude installed system-wide, like Homebrew or PostgreSQL. Every OS user on the machine can use the AI platform. Each person has their own identity, role, and sessions. The admin has operational oversight.

## What We Have Today

- Single-user install: everything lives under one user's home directory
- Daemon runs as the installing user
- TUI assumes the person sitting at it is the admin
- MCP socket (`/tmp/teleclaude.sock`) is open — no caller authentication
- All sessions in one DB, no ownership scoping
- Config (including secrets) is a single `config.yml`
- Doc snippets and index live in the project tree and `~/.teleclaude/docs/`

## What Needs to Change

### 1. Installation Layout

**System-wide shared resources** go to a standard location:

- `/usr/local/share/teleclaude/` — shared documentation, global snippets, index
- This is where the doc snippets that all users consume live
- Analogous to `/usr/local/share/` conventions (man pages, etc.)

**Per-user personal config and data:**

- `~/.teleclaude/` for each OS user — personal config, session transcripts, preferences
- Each user's session data lives in their own home dir
- Personal agent artifacts, project-specific overrides, etc.

### 2. Daemon & Service Model

The daemon needs to run system-wide:

- Runs under a dedicated `teleclaude` service user (like `_postgres`, `_mysql`)
- Managed by `launchd` (macOS) or `systemd` (Linux)
- Owns the shared DB and listens on a well-known socket
- Does NOT run as a regular user account

### 3. Identity & Authentication

**The critical problem: how does the daemon know WHO is connecting?**

Unix socket peer credentials (`SO_PEERCRED` on Linux, `LOCAL_PEERCRED` on macOS):

- When a client connects to the Unix socket, the kernel provides the connecting process's UID/GID
- The daemon maps UID → OS username → TeleClaude person → role
- No passwords, no tokens — the OS handles authentication
- If the UID doesn't map to any configured person → role is `public` (least privilege)

TUI sessions:

- The TUI runs as the logged-in OS user
- Connects to the daemon socket → daemon reads UID → resolves identity and role
- Admin sees all sessions; member sees only their own sessions + shared project data

External adapters (Telegram, Discord):

- These connect through the adapter layer, not the Unix socket
- Identity resolution works as today (chat ID → person → role)
- No change needed here

### 4. Config Separation

The current single `config.yml` must split:

**System config** (owned by root/teleclaude service user, readable by all):

- People definitions (name, identity keys, role)
- Project definitions
- Domain configuration
- Adapter settings (which adapters are enabled)

**Secrets** (owned by root/teleclaude service user, NOT readable by regular users):

- API keys (Anthropic, OpenAI, etc.)
- Adapter tokens (Telegram bot token, Discord bot token)
- Database credentials if applicable

**Per-user config** (`~/.teleclaude/config.yml` or similar):

- Personal preferences (thinking mode, default model)
- Project-specific overrides
- Nothing security-sensitive

### 5. Session Ownership & Visibility

Every session has an owner (the OS user who started it).

**Visibility rules:**

- Admin sees ALL sessions (metadata always, transcripts on explicit access)
- Member sees their OWN sessions only
- Public sees nothing in the session list

**Admin observability — the design decision:**

We discussed this at length. The AI is a shared system resource. Admin needs operational visibility. But sessions contain thinking — half-formed ideas, personal questions, mistakes. That's more intimate than command history.

**Decision: observable metadata, gated content.**

- Admin always sees: session list, owner, timestamp, project, duration, cost/tokens, status
- Admin does NOT see session transcripts by default (no ambient surveillance)
- Admin CAN access transcripts — it's an explicit action, and the system logs that access happened
- Every user sees a notice at session start: "Sessions on this system are subject to admin audit"
- There are NO private sessions. The shared system is a shared resource. If someone needs a private AI conversation, they use their own API key on their own machine.

**TUI grouping for admin:**

- Default view stays grouped by project (the natural unit of work)
- Sessions owned by other people show with an owner badge
- Filter by person is available but not the default
- Mental model: "the system's activity", not "people's activity"
- No separate "people" tab — that's surveillance UX

### 6. Doc Snippet Access

This is where the current doc-access-control feature directly enables multi-user:

- Snippets have `role: public | member | admin` in frontmatter
- The daemon resolves the caller's role from their session
- `get_context` filters snippets by role rank comparison
- A member connecting to a shared project sees member + public docs
- A public user sees only public docs
- An admin sees everything

No changes needed to the role system — it was built for this.

### 7. File Permissions

System-wide install needs proper file ownership:

- `/usr/local/share/teleclaude/` — owned by `teleclaude:teleclaude`, world-readable
- Shared DB — owned by `teleclaude` service user, not directly accessible by regular users
- Per-user `~/.teleclaude/` — owned by the respective user
- MCP socket — owned by `teleclaude`, permissions allow group access or use `SO_PEERCRED`
- Snippet files — readable by all, writable only by admin/member depending on scope

### 8. The Homebrew Analogy (and Its Limits)

Brew installs binaries system-wide, each user runs them in their own context. Works because brew packages are stateless tools.

TeleClaude is a **stateful service** — daemon, database, sessions, secrets. Closer analogies:

- **PostgreSQL**: system-wide daemon, per-user authentication, role-based access
- **Docker**: system daemon, users added to `docker` group for access, socket-based auth
- **CUPS** (printing): system service, per-user job visibility, admin oversight

## Open Questions

1. **Database architecture**: Single shared SQLite DB owned by the service user? Or per-user DBs with a central session registry? SQLite doesn't handle concurrent writers well — may need to move to something else for the shared parts.

2. **Agent binary access**: AI agent CLIs (claude, gemini, codex) need API keys. If the daemon runs agent sessions, it holds the keys. But if users run agents directly, they need their own keys or a credential proxy.

3. **Worktree isolation**: Git worktrees are per-project. In multi-user mode, two people working on the same project need separate worktrees or coordination to avoid conflicts.

4. **Cost allocation**: If the admin is paying for API usage, they need per-user cost tracking. Session metadata should include token counts and model used, attributed to the owner.

5. **Migration path**: How does an existing single-user install migrate to system-wide? Can we make it non-destructive?

6. **macOS vs Linux**: `launchd` vs `systemd`, `LOCAL_PEERCRED` vs `SO_PEERCRED`, `/usr/local/share` vs `/opt` or `/usr/share`. Need to handle both.

## What This Does NOT Include

- Web-based multi-user (that's the web-interface todo)
- Remote multi-machine access (that's the existing Redis/peer system)
- Billing or subscription management
- User self-registration (admin manages people in config)

## Dependencies

- `doc-access-control` — role system must land first (in progress)
- Session identity model is stable
- People/identity configuration system exists

## Rough Sizing

This is a large architectural project, not a single session's work. Likely needs:

- Design phase: deployment layout, config schema, socket auth protocol
- Daemon phase: service user, systemd/launchd units, socket authentication
- TUI phase: multi-user session list, owner badges, admin visibility
- Config phase: split system/secrets/personal, migration tool
- Testing: multi-user scenarios, permission boundaries, role escalation prevention
