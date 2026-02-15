# Help Desk Platform Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Turn TeleClaude into a two-plane help desk platform — customer ingress on any adapter, operator workspace on Discord — with identity-scoped memory, escalation tooling, admin relay channels, internal pub/sub channels, and a standalone operator workspace.

**Architecture:** The platform extends the existing daemon with per-customer memory scoping (identity_key on memory_observations), Discord/Telegram identity resolution, customer-role MCP filtering, an escalation MCP tool (`teleclaude__escalate`), admin relay channels (Discord threads bridging to customer platforms), audience-tagged doc snippets, Redis Stream internal channels, and a standalone operator workspace bootstrapped by `telec init`. Memory extraction runs as an idempotent job with two trigger paths (idle-detected and cron sweep).

**Tech Stack:** Python 3.12, SQLAlchemy/SQLModel, Redis Streams, Pydantic config, MCP tools, doc snippet frontmatter YAML, discord.py

**Design doc:** `docs/project/design/architecture/help-desk-platform.md`

---

## Work Package 1: Identity-Scoped Memory (Foundation)

### Task 1: Add identity_key column to memory_observations

**Files:**

- Modify: `teleclaude/core/db_models.py:146-167`
- Modify: `teleclaude/memory/store.py:25-85`
- Modify: `teleclaude/memory/api_routes.py:18-26,44-72,108-114`
- Modify: `teleclaude/memory/context/builder.py:17-68`
- Test: `tests/unit/test_memory_store.py` (existing or create)

**Step 1: Add identity_key to MemoryObservation model**

In `teleclaude/core/db_models.py`, add to `MemoryObservation` class after the `project` field (line ~154):

```python
identity_key: Optional[str] = Field(default=None, sa_column=Column(String, nullable=True))
```

**Step 2: Add identity_key to SaveObservationRequest**

In `teleclaude/memory/api_routes.py`, add to `SaveObservationRequest` (line ~23):

```python
identity_key: str | None = None
```

**Step 3: Thread identity_key through save_observation()**

In `teleclaude/memory/store.py`, both `save_observation()` and `save_observation_sync()` must pass `identity_key` from the request to the DB model.

**Step 4: Add identity_key query param to search and inject routes**

In `teleclaude/memory/api_routes.py`:

- `search` endpoint (line ~60): add `identity_key: str | None = None` param, filter query accordingly
- `inject` endpoint (line ~108): add `identity_key: str | None = None` param, pass to `generate_context()`

**Step 5: Update generate_context_sync() for identity-scoped queries**

In `teleclaude/memory/context/builder.py`, modify the SQL query in `generate_context_sync()` (line ~45):

```sql
WHERE project = :project
  AND (identity_key IS NULL OR identity_key = :identity_key)
ORDER BY created_at_epoch DESC
LIMIT 50
```

When `identity_key` is None, only project-level memories are returned (backward-compatible).

**Step 6: Write migration for existing data**

The column must be added to the live database. Add a migration in `teleclaude/core/migrations/` that runs:

```sql
ALTER TABLE memory_observations ADD COLUMN identity_key TEXT;
CREATE INDEX idx_memory_identity ON memory_observations(project, identity_key);
```

**Step 7: Run tests and verify**

Run: `make test`

**Step 8: Commit**

```
feat(memory): add identity_key scoping to memory observations
```

---

### Task 2: Add identity_key derivation helper

**Files:**

- Modify: `teleclaude/core/identity.py`
- Test: `tests/unit/test_identity.py`

**Step 1: Add derive_identity_key() function**

In `teleclaude/core/identity.py`, add after the IdentityContext dataclass:

```python
def derive_identity_key(adapter_metadata: "SessionAdapterMetadata") -> str | None:
    """Derive identity key from adapter metadata.

    Format: {platform}:{platform_user_id}
    Returns None if no identity can be determined.
    """
    if adapter_metadata.discord and adapter_metadata.discord.user_id:
        return f"discord:{adapter_metadata.discord.user_id}"
    if adapter_metadata.telegram and getattr(adapter_metadata.telegram, "user_id", None):
        return f"telegram:{adapter_metadata.telegram.user_id}"
    if adapter_metadata.web and adapter_metadata.web.email:
        return f"web:{adapter_metadata.web.email}"
    return None
```

**Step 2: Write test for derive_identity_key()**

Test each platform case + None fallback.

**Step 3: Run tests**

Run: `pytest tests/unit/test_identity.py -v`

**Step 4: Commit**

```
feat(identity): add identity_key derivation from adapter metadata
```

---

## Work Package 2: Adapter Metadata Fixes

### Task 3: Add user_id to TelegramAdapterMetadata

**Files:**

- Modify: `teleclaude/core/models.py:130-138`
- Test: `tests/unit/test_models.py`

**Step 1: Add user_id field**

In `teleclaude/core/models.py`, add to `TelegramAdapterMetadata` (after line ~138):

```python
user_id: Optional[int] = None
```

**Step 2: Update Telegram adapter to populate user_id**

Find where Telegram sessions are created and ensure `user_id` is set on the `TelegramAdapterMetadata` from the identity resolution context. Search for where `TelegramAdapterMetadata` is constructed (likely in Telegram message handler).

**Step 3: Verify serialization/deserialization**

Check `SessionAdapterMetadata.to_json()` and `from_json()` — Pydantic/dataclass fields are typically auto-serialized, but verify the Telegram deserialization path (lines 261-283) handles the new field.

**Step 4: Run tests and commit**

```
feat(telegram): persist user_id in adapter metadata for identity derivation
```

---

### Task 4: Add Discord identity resolution

**Files:**

- Modify: `teleclaude/config/schema.py:109-117`
- Modify: `teleclaude/core/identity.py:31-35,79-81,126-133`
- Test: `tests/unit/test_identity.py`

**Step 1: Add DiscordCreds to config schema**

In `teleclaude/config/schema.py`, add after `TelegramCreds` (line ~112):

```python
class DiscordCreds(BaseModel):
    user_id: str  # Discord user IDs are snowflakes (strings)
```

Add to `CredsConfig` (line ~117):

```python
discord: Optional[DiscordCreds] = None
```

**Step 2: Add \_by_discord_user_id lookup map**

In `teleclaude/core/identity.py` `IdentityResolver.__init__()` (line ~35):

```python
self._by_discord_user_id: dict[str, PersonEntry] = {}
```

In `_load_config()` (after line ~81):

```python
discord_creds = getattr(person_conf.creds, "discord", None) if person_conf.creds else None
if discord_creds:
    self._by_discord_user_id[discord_creds.user_id] = person
```

**Step 3: Update Discord resolution in resolve()**

The Discord origin handler (lines 126-133) currently always returns `CUSTOMER_ROLE`. Modify to check `_by_discord_user_id` first:

```python
if origin == InputOrigin.DISCORD:
    discord_user_id = context.get("discord_user_id")
    if discord_user_id and discord_user_id in self._by_discord_user_id:
        person = self._by_discord_user_id[discord_user_id]
        return IdentityContext(
            person_name=person.name,
            person_email=person.email,
            person_role=person.role,
            platform="discord",
            platform_user_id=discord_user_id,
        )
    return IdentityContext(
        person_role="customer",
        platform="discord",
        platform_user_id=discord_user_id,
    )
```

**Step 4: Write tests for Discord identity resolution**

Test: known user -> configured role, unknown user -> customer role.

**Step 5: Run tests and commit**

```
feat(identity): add Discord person config lookup via discord_user_id
```

---

## Work Package 3: MCP Customer Role & Escalation Gating

### Task 5: Add CUSTOMER_EXCLUDED_TOOLS tier and escalation gating

**Files:**

- Modify: `teleclaude/mcp/role_tools.py:17-73`
- Modify: `teleclaude/constants.py:42-46`
- Test: `tests/unit/test_role_tools.py`

**Step 1: Add HUMAN_ROLE_CUSTOMER constant**

In `teleclaude/constants.py` (line ~46), add:

```python
HUMAN_ROLE_CUSTOMER = "customer"
```

Update `HUMAN_ROLES` tuple to include it:

```python
HUMAN_ROLES = (HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER)
```

**Step 2: Define CUSTOMER_EXCLUDED_TOOLS**

In `teleclaude/mcp/role_tools.py`, add after `UNAUTHORIZED_EXCLUDED_TOOLS` (line ~50):

```python
CUSTOMER_EXCLUDED_TOOLS: set[str] = UNAUTHORIZED_EXCLUDED_TOOLS | {
    "teleclaude__list_sessions",
    "teleclaude__list_todos",
}
```

This is the superset of `UNAUTHORIZED_EXCLUDED_TOOLS` plus any remaining tools customers should not see. The escalation tool (`teleclaude__escalate`) is explicitly NOT in this set — customers must see it.

**Step 3: Add escalation tool to non-customer exclusion lists**

Add `"teleclaude__escalate"` to these sets so only customer sessions see it:

```python
WORKER_EXCLUDED_TOOLS = {
    ...,
    "teleclaude__escalate",
}

MEMBER_EXCLUDED_TOOLS = {
    ...,
    "teleclaude__escalate",
}

UNAUTHORIZED_EXCLUDED_TOOLS = {
    ...,
    "teleclaude__escalate",
}
```

**Step 4: Add customer branch to get_excluded_tools()**

In `get_excluded_tools()` (line ~59), add before the member check:

```python
if human_role == HUMAN_ROLE_CUSTOMER:
    excluded.update(CUSTOMER_EXCLUDED_TOOLS)
    return excluded  # Customer tier is terminal — no further layering
```

**Step 5: Write tests**

- `get_excluded_tools(role=None, human_role="customer")` returns CUSTOMER_EXCLUDED_TOOLS
- `get_excluded_tools(role=None, human_role="customer")` does NOT include `teleclaude__escalate`
- `get_excluded_tools(role=None, human_role="admin")` DOES include `teleclaude__escalate` (from UNAUTHORIZED? No — admin sees everything). Actually: admin has no exclusions, so `teleclaude__escalate` is visible. But for member/worker/unauthorized, it IS excluded.
- `get_excluded_tools(role="worker", human_role=None)` includes `teleclaude__escalate`

**Step 6: Run tests and commit**

```
feat(mcp): add CUSTOMER_EXCLUDED_TOOLS tier and gate escalation tool to customer sessions
```

---

## Work Package 4: Audience Tagging

### Task 6: Add audience field to doc snippet infrastructure

**Files:**

- Modify: `teleclaude/docs_index.py:98-104`
- Modify: `teleclaude/context_selector.py` (SnippetMeta dataclass, \_include_snippet, build_context_output)
- Modify: `teleclaude/resource_validation.py` (frontmatter validation)
- Modify: `teleclaude/constants.py`
- Test: `tests/unit/test_context_selector.py`

**Step 1: Add AUDIENCE_VALUES constant**

In `teleclaude/constants.py`:

```python
AUDIENCE_VALUES = ("admin", "member", "help-desk", "public")
```

**Step 2: Add audience to SnippetEntry TypedDict**

In `teleclaude/docs_index.py` (line ~104):

```python
audience: NotRequired[list[str]]
```

**Step 3: Add audience to SnippetMeta dataclass**

In `teleclaude/context_selector.py`, add to the `SnippetMeta` dataclass:

```python
audience: list[str] = field(default_factory=lambda: ["admin"])
```

**Step 4: Extract audience during index loading**

In `_load_index()`, when building SnippetMeta from index entries, read `audience` field (defaulting to `["admin"]`).

**Step 5: Add audience to index generation**

In `teleclaude/docs_index.py`, when building index entries from frontmatter, include `audience` field if present.

**Step 6: Add optional audience validation**

In `teleclaude/resource_validation.py`, validate that `audience` values (if present) are from `AUDIENCE_VALUES`. This is a warning, not an error — additive field.

**Step 7: Run tests and commit**

```
feat(docs): add audience field to doc snippet frontmatter for role-filtered context
```

---

### Task 7: Add audience filtering to get_context

**Files:**

- Modify: `teleclaude/context_selector.py` (\_include_snippet closure)
- Modify: `teleclaude/mcp/handlers.py:955-1013`
- Test: `tests/unit/test_context_selector.py`

**Step 1: Thread human_role through to build_context_output()**

In `teleclaude/mcp/handlers.py` `teleclaude__get_context()`, resolve `human_role` from the calling session (already available via `caller_session_id` -> `session.human_role`). Pass as new parameter to `build_context_output()`.

**Step 2: Filter snippets by audience in \_include_snippet()**

In `teleclaude/context_selector.py`, modify the `_include_snippet()` closure:

```python
# If no human_role or human_role is admin -> see everything
# If human_role is customer -> only see snippets tagged "public" or "help-desk"
# If human_role is member -> see "admin", "member", "help-desk", "public"
```

Default: no audience field -> treated as `["admin"]`.

**Step 3: Write tests for audience filtering**

**Step 4: Run tests and commit**

```
feat(context): filter doc snippets by audience based on caller's human_role
```

---

## Work Package 5: Session Schema Extensions

### Task 8: Add bookkeeping and relay columns to sessions table

**Files:**

- Modify: `teleclaude/core/schema.sql:3-37`
- Modify: `teleclaude/core/models.py:437-474`
- Modify: `teleclaude/core/db_models.py:16-57` (Session SQLModel)
- Modify: `teleclaude/core/db.py` (create_session, \_to_core_session)
- Create: migration for existing databases

**Step 1: Add columns to schema.sql**

After `lifecycle_status TEXT DEFAULT 'active'` (line 34), add:

```sql
last_memory_extraction_at TEXT,
help_desk_processed_at TEXT,
relay_status TEXT,                -- NULL (normal) or 'active' (relay mode)
relay_discord_channel_id TEXT,    -- Discord thread ID for escalation relay
relay_started_at TEXT,            -- Timestamp of relay activation
human_email TEXT,
human_role TEXT
```

Note: `human_email` and `human_role` already exist in `db_models.py` (lines 56-57) but are missing from `schema.sql`. Add them for completeness.

**Step 2: Add fields to Session dataclass**

In `teleclaude/core/models.py` (after line ~474):

```python
last_memory_extraction_at: Optional[datetime] = None
help_desk_processed_at: Optional[datetime] = None
relay_status: Optional[str] = None
relay_discord_channel_id: Optional[str] = None
relay_started_at: Optional[datetime] = None
```

**Step 3: Add fields to db_models.Session**

In `teleclaude/core/db_models.py`, add to the `Session` SQLModel class (after line ~57):

```python
last_memory_extraction_at: Optional[str] = None
help_desk_processed_at: Optional[str] = None
relay_status: Optional[str] = None
relay_discord_channel_id: Optional[str] = None
relay_started_at: Optional[str] = None
```

**Step 4: Update \_to_core_session() and create_session()**

In `teleclaude/core/db.py`, ensure the new fields are serialized/deserialized. Add datetime parsing for the new timestamp fields in `Session.from_dict()` and serialization in `Session.to_dict()`.

**Step 5: Write migration**

```sql
ALTER TABLE sessions ADD COLUMN last_memory_extraction_at TEXT;
ALTER TABLE sessions ADD COLUMN help_desk_processed_at TEXT;
ALTER TABLE sessions ADD COLUMN relay_status TEXT;
ALTER TABLE sessions ADD COLUMN relay_discord_channel_id TEXT;
ALTER TABLE sessions ADD COLUMN relay_started_at TEXT;
```

**Step 6: Run tests and commit**

```
feat(sessions): add bookkeeping and relay state columns
```

---

## Work Package 6: Identity-Aware Context Injection

### Task 9: Thread identity_key through hook receiver

**Files:**

- Modify: `teleclaude/hooks/receiver.py:77-85,211-224`
- Modify: `teleclaude/memory/context/builder.py:34-68`

**Step 1: Resolve identity_key in \_print_memory_injection()**

In `teleclaude/hooks/receiver.py` `_print_memory_injection()` (line ~211):

1. Read the session from DB using the session_id (available from hook context)
2. Call `derive_identity_key(session.adapter_metadata)` to get the identity key
3. Pass `identity_key` to `_get_memory_context()`

**Step 2: Update \_get_memory_context() to accept identity_key**

```python
def _get_memory_context(project_name: str, identity_key: str | None = None) -> str:
    from teleclaude.memory.context import generate_context_sync
    db_path = str(config.database.path)
    return generate_context_sync(project_name, db_path, identity_key=identity_key)
```

**Step 3: Update generate_context_sync() signature**

Already handled in Task 1 Step 5.

**Step 4: Run tests and commit**

```
feat(hooks): inject identity-scoped memories on SessionStart
```

---

## Work Package 7: Help Desk Bootstrap

### Task 10: Create help desk templates

**Files:**

- Create: `templates/help-desk/AGENTS.master.md`
- Create: `templates/help-desk/README.md`
- Create: `templates/help-desk/teleclaude.yml`
- Create: `templates/help-desk/.gitignore`
- Create: `templates/help-desk/docs/global/organization/baseline.md`
- Create: `templates/help-desk/docs/global/organization/spec/about.md`
- Create: `templates/help-desk/docs/project/baseline.md`
- Create: `templates/help-desk/docs/project/policy/escalation.md`
- Create: `templates/help-desk/docs/project/procedure/escalation.md`
- Create: `templates/help-desk/docs/project/spec/tools/escalation.md`
- Create: `templates/help-desk/docs/project/design/help-desk-overview.md`

**Step 1: Create each template file**

See design doc section "Help Desk Bootstrap Routine -> Template contents" for exact content descriptions.

Key additions from the escalation design:

- `docs/project/policy/escalation.md` — starter escalation policy: when to escalate (billing, security, low confidence, explicit human request), thresholds
- `docs/project/procedure/escalation.md` — step-by-step: recognize trigger -> call `teleclaude__escalate` -> inform customer help is on the way -> wait for `@agent` handback
- `docs/project/spec/tools/escalation.md` — tool contract: parameters (`customer_name` required, `reason` required, `context_summary` optional), return value, behavior (creates Discord thread, sets relay, sends notification)

**Step 2: Commit**

```
feat(templates): add help desk project skeleton with escalation docs
```

---

### Task 11: Add help_desk_dir to computer config

**Files:**

- Modify: `teleclaude/config/schema.py`
- Modify: config loader if needed

**Step 1: Add help_desk_dir field**

Add to the appropriate computer config class:

```python
help_desk_dir: Optional[str] = None  # Path to help desk project, default: sibling of teleclaude
```

**Step 2: Commit**

```
feat(config): add help_desk_dir to computer config schema
```

---

### Task 12: Implement bootstrap routine in init flow

**Files:**

- Modify: `teleclaude/project_setup/init_flow.py:16-34`
- Create: `teleclaude/project_setup/help_desk_bootstrap.py`

**Step 1: Create help_desk_bootstrap module**

```python
def bootstrap_help_desk(teleclaude_root: Path) -> None:
    """Idempotent bootstrap for help desk workspace."""
    help_desk_dir = _resolve_help_desk_dir(teleclaude_root)
    if help_desk_dir.exists():
        logger.info("Help desk directory already exists: %s", help_desk_dir)
        return

    # Copy templates
    template_dir = teleclaude_root / "templates" / "help-desk"
    shutil.copytree(template_dir, help_desk_dir)

    # git init
    subprocess.run(["git", "init"], cwd=help_desk_dir, check=True)

    # telec init inside the new dir
    from teleclaude.project_setup.init_flow import init_project
    init_project(help_desk_dir)

    # Initial commit
    subprocess.run(["git", "add", "."], cwd=help_desk_dir, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial help desk scaffold"],
        cwd=help_desk_dir, check=True
    )
```

**Step 2: Hook into init_project() flow**

Call `bootstrap_help_desk()` from `init_project()` after the main setup steps, guarded by config check.

**Step 3: Run tests and commit**

```
feat(init): add idempotent help desk workspace bootstrap
```

---

## Work Package 8: Knowledge Authoring Command

### Task 13: Create /author-knowledge global command

**Files:**

- Create: `agents/commands/author-knowledge.md`

**Step 1: Write the command**

Follow the command schema: frontmatter (description, argument-hint), activation line, Required reads, Purpose, Inputs, Outputs, Steps.

Required reads should reference:

- `@~/.teleclaude/docs/general/procedure/doc-snippet-authoring.md`
- `@~/.teleclaude/docs/general/spec/snippet-authoring-schema.md`

Activation: "You are now the Knowledge Author."

Steps should cover the conversational extraction -> taxonomy classification -> doc snippet creation -> telec sync -> commit flow.

**Step 2: Run telec sync**

```bash
telec sync
```

**Step 3: Commit**

```
feat(commands): add global /author-knowledge command for brain-dump documentation
```

---

## Work Package 9: Internal Channels

### Task 14: Implement channel publish API and MCP tool

**Files:**

- Create: `teleclaude/channels/publisher.py`
- Create: `teleclaude/channels/consumer.py`
- Modify: `teleclaude/mcp/handlers.py` (add teleclaude\_\_publish, teleclaude\_\_channels_list)
- Modify: `teleclaude/api/routes.py` (add POST /api/channels/{name}/publish)

**Step 1: Create publisher module**

Uses Redis Streams: `XADD channel:{project}:{topic} * payload <json>`.

```python
async def publish(channel: str, payload: dict) -> str:
    """Publish message to a Redis Stream channel. Returns message ID."""
    redis = get_redis_client()
    msg_id = await redis.xadd(channel, {"payload": json.dumps(payload)})
    return msg_id
```

**Step 2: Create consumer module**

Uses Redis consumer groups for exactly-once processing:

```python
async def consume(channel: str, group: str, consumer: str) -> list[dict]:
    """Read pending messages from a channel consumer group."""
    ...
```

**Step 3: Add MCP tools**

- `teleclaude__publish(channel: str, payload: dict)` — publish to a channel
- `teleclaude__channels_list()` — list channels and their subscriptions from config

**Step 4: Add HTTP API route**

`POST /api/channels/{name}/publish` — REST endpoint for the same operation.

**Step 5: Run tests and commit**

```
feat(channels): add Redis Stream internal channels with publish/consume
```

---

### Task 15: Implement channel consumer worker

**Files:**

- Create: `teleclaude/channels/worker.py`
- Modify: `teleclaude/daemon/` (register background task)

**Step 1: Create consumer worker**

A background task that polls subscribed channels from `teleclaude.yml` config, dispatches to notification or agent targets.

**Step 2: Register as daemon background task**

**Step 3: Add channel subscription config schema**

In `teleclaude/config/schema.py`, add:

```python
class ChannelSubscription(BaseModel):
    channel: str
    filter: Optional[dict] = None
    target: dict  # notification or project+command
```

**Step 4: Run tests and commit**

```
feat(channels): add consumer worker for channel subscription routing
```

---

## Work Package 10: Customer Session Lifecycle

### Task 16: Implement idle compaction detection

**Files:**

- Modify: daemon idle detection logic
- Modify: session lifecycle management

**Step 1: Add customer idle threshold config**

Configurable idle threshold (default 30 minutes) for customer sessions.

**Step 2: Implement idle detection for customer sessions**

When a customer session hits idle threshold:

1. Do NOT kill the session (unlike admin idle timeout)
2. Spawn memory extraction job
3. After extraction completes -> inject `/compact`
4. Do NOT update `last_message_sent`

**Step 3: Ensure 72h sweep is the only death path**

Customer sessions with `human_role == "customer"` skip standard idle timeout. Only the 72h inactivity sweep ends them.

**Step 4: Run tests and commit**

```
feat(lifecycle): add customer idle compaction without session termination
```

---

## Work Package 11: Memory Extraction Job

### Task 17: Create help-desk-session-review job

**Files:**

- Create: `jobs/help_desk_session_review.py`

**Step 1: Create job class**

```python
class HelpDeskSessionReviewJob(Job):
    name = "help-desk-session-review"

    def run(self) -> JobResult:
        # 1. Find sessions needing processing
        # 2. For each: read transcript since last_memory_extraction_at
        # 3. Extract personal memories (identity-scoped)
        # 4. Extract business memories (project-scoped)
        # 5. Extract actionable items -> publish to channels
        # 6. Update bookkeeping timestamps
        return JobResult(success=True, message=f"Processed {count} sessions")
```

**Step 2: Add job config to help desk teleclaude.yml template**

```yaml
jobs:
  help-desk-session-review:
    when:
      every: '30m'
    agent: claude
    thinking_mode: fast
```

**Step 3: Write tests and commit**

```
feat(jobs): add help-desk-session-review extraction job
```

---

### Task 18: Create help-desk-intelligence job

**Files:**

- Create: `jobs/help_desk_intelligence.py`

**Step 1: Create job class**

Queries recent business memories, detects patterns, generates digest, publishes to intelligence channel.

**Step 2: Add job config**

```yaml
jobs:
  help-desk-intelligence:
    when:
      every: '1d'
      at: '06:00'
    agent: claude
    thinking_mode: med
```

**Step 3: Commit**

```
feat(jobs): add help-desk-intelligence daily digest job
```

---

## Work Package 12: Operator Brain

### Task 19: Write operator brain template

**Files:**

- Modify: `templates/help-desk/AGENTS.master.md` (expand from Task 10 skeleton)

**Step 1: Write complete operator brain**

Following design doc section "Operator Brain" — identity, knowledge access, memory awareness, interaction style, observer interests, escalation rules, idle routines.

The operator brain MUST include a `## Required reads` section referencing the escalation docs:

```markdown
## Required reads

- @docs/project/policy/escalation.md
- @docs/project/procedure/escalation.md
- @docs/project/spec/tools/escalation.md
```

These get inlined at `telec sync` so the operator knows when, how, and with what tool to escalate.

**Step 2: Run telec sync in templates context**

Verify the AGENTS.master.md compiles correctly.

**Step 3: Commit**

```
feat(templates): expand operator brain with full help desk persona, escalation awareness, and routines
```

---

## Work Package 13: Escalation Tool

### Task 20: Add escalation_channel_id to Discord config

**Files:**

- Modify: `teleclaude/config/__init__.py:171-175` (DiscordConfig dataclass)
- Modify: `teleclaude/config/__init__.py:349` (DEFAULTS dict)
- Modify: `teleclaude/config/__init__.py:654-656` (config loader)

**Step 1: Add escalation_channel_id field**

In `teleclaude/config/__init__.py`, add to `DiscordConfig` (after `help_desk_channel_id` on line 175):

```python
@dataclass
class DiscordConfig:
    enabled: bool
    token: str | None
    guild_id: int | None
    help_desk_channel_id: int | None
    escalation_channel_id: int | None  # NEW: Forum channel for admin relay threads
```

**Step 2: Add default**

In `DEFAULTS["discord"]` (line ~349):

```python
"escalation_channel_id": None,
```

**Step 3: Update config loader**

In the config loading function (line ~654), add parsing for `escalation_channel_id`:

```python
escalation_channel_id=(
    _parse_optional_int(discord_raw.get("escalation_channel_id")) if isinstance(discord_raw, dict) else None
),
```

**Step 4: Run tests and commit**

```
feat(config): add escalation_channel_id to Discord config
```

---

### Task 21: Implement teleclaude\_\_escalate MCP handler

**Files:**

- Modify: `teleclaude/mcp/handlers.py` (add new handler after ~line 912)
- Modify: `teleclaude/adapters/discord_adapter.py` (add `create_escalation_thread` method)
- Test: `tests/unit/test_mcp_server.py`

**Step 1: Add escalation handler to MCP handlers**

In `teleclaude/mcp/handlers.py`, add after `teleclaude__send_result` (~line 912):

```python
async def teleclaude__escalate(
    self,
    customer_name: str,
    reason: str,
    context_summary: str | None = None,
) -> str:
    """Escalate a customer conversation to an admin.

    Creates a Discord thread in the escalation forum, notifies admins,
    and activates relay mode on the calling session.
    """
    # 1. Resolve calling session
    session = await self._get_caller_session()
    if not session:
        return "Error: Could not resolve calling session"

    # 2. Validate this is a customer session
    if session.human_role != "customer":
        return "Error: Escalation tool is only available in customer sessions"

    # 3. Create Discord escalation thread
    discord_adapter = self._get_discord_adapter()
    if not discord_adapter:
        return "Error: Discord adapter not available"

    thread_id = await discord_adapter.create_escalation_thread(
        customer_name=customer_name,
        reason=reason,
        context_summary=context_summary,
        session_id=session.session_id,
    )

    # 4. Set relay state on session
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    await self._update_session_fields(session.session_id, {
        "relay_status": "active",
        "relay_discord_channel_id": str(thread_id),
        "relay_started_at": now.isoformat(),
    })

    # 5. Send notification to admins
    await self._send_escalation_notification(
        customer_name=customer_name,
        reason=reason,
        session_id=session.session_id,
    )

    return f"Escalation created. Admin notified. Relay channel active (thread {thread_id})."
```

**Step 2: Add create_escalation_thread to Discord adapter**

In `teleclaude/adapters/discord_adapter.py`, add method:

```python
async def create_escalation_thread(
    self,
    customer_name: str,
    reason: str,
    context_summary: str | None,
    session_id: str,
) -> int:
    """Create a thread in the escalation forum channel."""
    escalation_channel_id = config.discord.escalation_channel_id
    if not escalation_channel_id:
        raise AdapterError("DISCORD_ESCALATION_CHANNEL_ID not configured")

    forum = await self._get_channel(escalation_channel_id)
    if forum is None:
        raise AdapterError(f"Escalation channel {escalation_channel_id} not found")

    # Build opening message
    body = f"**Reason:** {reason}"
    if context_summary:
        body += f"\n\n**Context:** {context_summary}"
    body += f"\n\n*Session: {session_id}*"

    thread, _ = await forum.create_thread(
        name=customer_name,
        content=body,
    )
    return thread.id
```

**Step 3: Add helper methods to MCP handler**

- `_get_caller_session()` — resolve session from `caller_session_id`
- `_get_discord_adapter()` — get the running Discord adapter instance
- `_update_session_fields()` — update arbitrary session fields in DB
- `_send_escalation_notification()` — enqueue notification via the outbox

**Step 4: Write tests**

- Escalation creates thread and sets relay state
- Escalation fails gracefully when Discord unavailable
- Escalation rejected for non-customer sessions

**Step 5: Run tests and commit**

```
feat(mcp): implement teleclaude__escalate tool with Discord relay activation
```

---

## Work Package 14: Admin Relay Channel

### Task 22: Message routing diversion for relay mode

**Files:**

- Modify: `teleclaude/adapters/discord_adapter.py:341-376` (\_handle_on_message)
- Modify: other adapters (Telegram) if they handle customer sessions

**Step 1: Add relay check to adapter message handling**

In the Discord adapter's `_handle_on_message()` (line 341), after session resolution (line 350):

```python
session = await self._resolve_or_create_session(message)
if not session:
    return

# Check relay mode — divert customer messages to relay thread
if session.relay_status == "active" and session.relay_discord_channel_id:
    await self._forward_to_relay_thread(session, text, message)
    return  # Do NOT dispatch to tmux
```

Implement `_forward_to_relay_thread()`:

```python
async def _forward_to_relay_thread(
    self, session: "Session", text: str, message: object
) -> None:
    """Forward customer message to the relay Discord thread."""
    thread = await self._get_channel(int(session.relay_discord_channel_id))
    if thread is None:
        logger.error("Relay thread %s not found", session.relay_discord_channel_id)
        return

    # Determine customer display name
    author = getattr(message, "author", None)
    name = getattr(author, "display_name", None) or "Customer"
    platform = session.last_input_origin or "unknown"

    await thread.send(f"**{name}** ({platform}): {text}")
```

**Step 2: Add relay check to Telegram adapter**

Same pattern: after session resolution, check `relay_status`. If active, forward the message to the Discord relay thread via the Discord adapter (cross-adapter call through the daemon).

**Step 3: Run tests and commit**

```
feat(adapters): divert customer messages to relay thread when relay is active
```

---

### Task 23: Admin-to-customer relay forwarding

**Files:**

- Modify: `teleclaude/adapters/discord_adapter.py:341-376` (\_handle_on_message)

**Step 1: Detect messages in relay threads**

In `_handle_on_message()`, before the normal session resolution flow, check if the message is in a relay thread (escalation forum channel):

```python
async def _handle_on_message(self, message: object) -> None:
    if self._is_bot_message(message):
        return

    text = getattr(message, "content", None)
    if not isinstance(text, str) or not text.strip():
        return

    # Check if this is a relay thread message
    channel = getattr(message, "channel", None)
    parent_id = getattr(channel, "parent_id", None)
    if parent_id and parent_id == config.discord.escalation_channel_id:
        await self._handle_relay_thread_message(message, text)
        return

    # ... existing session resolution flow
```

**Step 2: Implement \_handle_relay_thread_message()**

```python
async def _handle_relay_thread_message(self, message: object, text: str) -> None:
    """Handle admin message in a relay thread — forward to customer."""
    thread_id = str(getattr(getattr(message, "channel", None), "id", ""))

    # Find the session with this relay_discord_channel_id
    session = await self._find_session_by_relay_thread(thread_id)
    if not session:
        return  # Orphaned thread, ignore

    # Check for @agent handback (handled in Task 24)
    if self._is_agent_tag(text):
        await self._handle_agent_handback(session, text, thread_id)
        return

    # Forward admin message to customer's platform
    author = getattr(message, "author", None)
    admin_name = getattr(author, "display_name", None) or "Admin"
    await self._deliver_to_customer(session, f"{admin_name}: {text}")
```

**Step 3: Implement \_deliver_to_customer()**

Routes the message back to the customer via their originating platform adapter:

```python
async def _deliver_to_customer(self, session: "Session", text: str) -> None:
    """Deliver a message to the customer via their originating adapter."""
    origin = session.last_input_origin
    # Use the adapter client to fan-out to the correct adapter
    await self.client.deliver_to_session(session.session_id, text, origin=origin)
```

**Step 4: Implement \_find_session_by_relay_thread()**

Query the DB for a session where `relay_discord_channel_id == thread_id` and `relay_status == "active"`.

**Step 5: Run tests and commit**

```
feat(discord): forward admin relay messages to customer platform
```

---

### Task 24: `@agent` handback with context injection

**Files:**

- Modify: `teleclaude/adapters/discord_adapter.py` (add handback logic)

**Step 1: Implement \_is_agent_tag()**

Detect `@agent` in the message text. Check for both the Discord bot mention (`<@BOT_ID>`) and the text convention `@agent`:

```python
def _is_agent_tag(self, text: str) -> bool:
    """Check if message contains an @agent handback tag."""
    if "@agent" in text.lower():
        return True
    if self._client and self._client.user:
        bot_mention = f"<@{self._client.user.id}>"
        if bot_mention in text:
            return True
    return False
```

**Step 2: Implement \_handle_agent_handback()**

```python
async def _handle_agent_handback(
    self, session: "Session", text: str, thread_id: str
) -> None:
    """Collect relay messages and inject context back into AI session."""
    # 1. Collect messages from relay thread since relay_started_at
    messages = await self._collect_relay_messages(
        thread_id=thread_id,
        since=session.relay_started_at,
    )

    # 2. Compile into context block
    context_block = self._compile_relay_context(messages)

    # 3. Inject into AI session's tmux
    from teleclaude.core.tmux_bridge import inject_text
    inject_text(session.tmux_session_name, context_block)

    # 4. Clear relay state
    await self._update_session_fields(session.session_id, {
        "relay_status": None,
        "relay_discord_channel_id": None,
        "relay_started_at": None,
    })
```

**Step 3: Implement \_collect_relay_messages()**

Use Discord API to read thread history since `relay_started_at`:

```python
async def _collect_relay_messages(
    self, thread_id: str, since: datetime | None
) -> list[dict]:
    """Read all messages from a relay thread since the given timestamp."""
    thread = await self._get_channel(int(thread_id))
    if not thread:
        return []

    messages = []
    async for msg in thread.history(after=since, limit=200):
        if self._is_bot_message(msg):
            continue  # Skip the bot's own relay forwarding
        author = getattr(msg, "author", None)
        name = getattr(author, "display_name", None) or "Unknown"
        is_admin = not getattr(author, "bot", False)
        role = "Admin" if is_admin else "Customer"
        messages.append({
            "role": role,
            "name": name,
            "content": getattr(msg, "content", ""),
            "timestamp": getattr(msg, "created_at", None),
        })
    return messages
```

**Step 4: Implement \_compile_relay_context()**

```python
def _compile_relay_context(self, messages: list[dict]) -> str:
    """Compile relay messages into a context block for AI injection."""
    lines = [
        "[Admin Relay Conversation]",
        "The admin spoke directly with the customer. Here is the full exchange:",
        "",
    ]
    for msg in messages:
        lines.append(f"{msg['role']} ({msg['name']}): {msg['content']}")

    lines.extend([
        "",
        "The admin has handed the conversation back to you. Continue naturally,",
        "acknowledging what was discussed.",
    ])
    return "\n".join(lines)
```

**Step 5: Write tests**

- `@agent` triggers context collection and injection
- Relay state cleared after handback
- Messages collected since `relay_started_at` only
- Multiple handback cycles within one session work correctly

**Step 6: Run tests and commit**

```
feat(discord): implement @agent handback with relay context injection
```

---

## Execution Order Summary

| Phase          | Tasks           | Dependencies    |
| -------------- | --------------- | --------------- |
| **Foundation** | 1, 2, 3, 4, 5   | None            |
| **Infra**      | 6, 7, 8, 10, 11 | Phase 1         |
| **Config**     | 20              | None (parallel) |
| **Bootstrap**  | 12, 13          | Phase 1         |
| **Channels**   | 14, 15          | None (parallel) |
| **Lifecycle**  | 9, 16           | Tasks 1, 2      |
| **Escalation** | 21              | Tasks 5, 8, 20  |
| **Relay**      | 22, 23, 24      | Tasks 8, 21     |
| **Jobs**       | 17, 18          | Tasks 1, 9, 14  |
| **Polish**     | 19              | Tasks 6, 10, 12 |

Tasks within a phase can be worked in parallel where noted. The dependency graph is encoded above — a task only requires its listed dependencies, not the entire prior phase.

**Parallelism opportunities:**

- Tasks 1-5 + 14 + 20 can all run in parallel (no shared dependencies)
- Tasks 6-8 + 10-11 can run in parallel once Phase 1 is done
- Tasks 21-24 form a sequential chain (escalation -> relay diversion -> forwarding -> handback)
- Task 19 (operator brain) is the final integrator — it references everything else
