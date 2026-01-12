# Cache Population - Deferred Work Completion

## Problem Statement

The data-caching-pushing feature was marked as delivered but critical cache population logic was never implemented. The cache infrastructure exists but is never populated with remote data.

## What Was Designed But Not Delivered

### 1. Computers from Heartbeats

**Original Requirement (data-caching-pushing/requirements.md:82-84):**
> Computers | Heartbeats | 60s | Pushed by remotes | Auto-expire

**Gap:**
- `cache.update_computer()` method exists but is NEVER CALLED in production
- Heartbeats are received but don't populate the cache
- `cache.get_computers()` always returns empty list

**Required Fix:**
- When heartbeat is received from remote, call `cache.update_computer()` with computer info
- Computer info should auto-expire after 60s (TTL already designed)

---

### 2. Remote Projects Pull-Once

**Original Requirement (data-caching-pushing/requirements.md:85):**
> Remote Projects | Pull once | 5 min | On view access | TTL or 'r' key

**Gap:**
- `cache.set_projects()` method exists but is NEVER CALLED
- No mechanism to pull remote projects on view access
- No TTL-based refresh

**Required Fix:**
- When Sessions or Preparation view opens, check if remote projects are stale
- If stale or missing, pull from remote computers via MCP handler
- Store in cache with 5 min TTL

---

### 3. Initial Session Pull

**Original Requirement (data-caching-pushing/requirements.md:86):**
> Remote Sessions | Pull once + events | ∞ | Initial pull, then events

**Gap:**
- Events work (`cache.update_session()` IS called from redis_adapter)
- But no initial pull - cache starts empty
- Sessions only appear AFTER a remote event fires

**Required Fix:**
- When interest is first registered for "sessions", pull existing sessions from remotes
- Store in cache, then let events maintain

---

### 4. Todos Pull-Once

**Original Requirement (data-caching-pushing/requirements.md:88):**
> Todos | Pull once | 5 min | On Preparation view | TTL or 'r' key

**Gap:**
- `cache.set_todos()` method exists but is NEVER CALLED
- `/projects-with-todos` only returns LOCAL projects
- No remote todo fetching

**Required Fix:**
- When Preparation view opens, pull todos for visible remote projects
- Store in cache with 5 min TTL

---

### 5. TTL-Based Auto-Refresh

**Original Requirement:**
> projects ───── pull once on view access ─────── TTL: 5 min
> todos ──────── pull once on view access ─────── TTL: 5 min

**Gap:**
- `is_stale()` method exists but never checked
- No refresh when TTL expires

**Required Fix:**
- Before returning cached data, check staleness
- If stale, trigger background re-fetch

---

### 6. Manual Refresh Re-Fetch

**Original Requirement:**
> Manual refresh works - 'r' key invalidates cache and re-fetches

**Gap:**
- 'r' key calls `cache.invalidate_all()`
- But no re-fetch is triggered after invalidation

**Required Fix:**
- After invalidation, trigger pull from remotes

---

## Data Population Matrix (What Must Be Implemented)

| Data | Trigger | Population Method | TTL |
|------|---------|-------------------|-----|
| Computers | Heartbeat received | `cache.update_computer()` | 60s auto-expire |
| Remote Projects | View access + stale | Pull via MCP → `cache.set_projects()` | 5 min |
| Remote Sessions | Interest registered | Pull via MCP → `cache.update_session()` | ∞ (events maintain) |
| Todos | Preparation view + stale | Pull via MCP → `cache.set_todos()` | 5 min |

## Success Criteria

1. **Remote computers appear in TUI** - Heartbeats populate cache
2. **Remote sessions appear on TUI startup** - Initial pull on interest
3. **Remote projects appear in tree** - Pull on view access
4. **Remote todos appear in Preparation** - Pull on view access
5. **Manual refresh works** - 'r' key re-fetches from remotes
6. **Stale data auto-refreshes** - TTL triggers re-fetch

## Related Files

- `teleclaude/core/cache.py` - Cache methods exist, need callers
- `teleclaude/adapters/redis_adapter.py` - Heartbeat handling, needs to call cache
- `teleclaude/adapters/rest_adapter.py` - View access triggers, needs pull logic
- `teleclaude/cli/tui/app.py` - Manual refresh, needs re-fetch after invalidate
