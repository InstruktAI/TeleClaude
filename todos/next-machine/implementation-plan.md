# Implementation Plan - Next Machine

## Architecture Overview

```
teleclaude/core/next_machine.py    # Core logic module
├── Shared Helpers
│   ├── resolve_slug()             # Roadmap parsing, slug extraction
│   ├── get_available_agent()      # Availability check + fallback selection
│   ├── check_file_exists()        # Simple path existence
│   ├── get_archive_path()         # Check if done/*-{slug}/ exists
│   ├── parse_impl_plan_done()     # Check Groups 1-4 completion
│   └── check_review_status()      # Review verdict parsing
│
├── Git Operations (GitPython)
│   ├── ensure_worktree()          # Create worktree if missing
│   └── has_uncommitted_changes()  # Check worktree dirty state
│
├── Response Formatters (plain text output)
│   ├── format_tool_call()         # Literal tool call for orchestrator
│   ├── format_error()             # Error message
│   ├── format_prepared()          # Ready for work message
│   └── format_complete()          # Work finalized message
│
└── Main Functions
    ├── next_prepare()             # Phase A state machine
    └── next_work()                # Phase B state machine

teleclaude/core/db.py              # Database extensions
├── agent_availability table
├── get_agent_availability()
├── mark_agent_unavailable()
└── clear_expired_availability()

teleclaude/mcp_server.py           # MCP tool definitions
├── teleclaude__next_prepare()
├── teleclaude__next_work()
└── teleclaude__mark_agent_unavailable()

bin/mcp-wrapper.py                 # Context injection
└── Inject cwd via os.getcwd()
```

---

## Group 1: Dependencies & Module Scaffold

- [ ] **Add GitPython dependency:** Add `GitPython>=3.1.0` to `pyproject.toml` dependencies
- [ ] **Create module file:** Create `teleclaude/core/next_machine.py` with imports
- [ ] **Define fallback matrices:** Create `PREPARE_FALLBACK` and `WORK_FALLBACK` dicts mapping task types to agent preferences

```python
# Example structure
PREPARE_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "prepare": [("claude", "slow"), ("gemini", "slow")],
}

WORK_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "build": [("gemini", "med"), ("claude", "med"), ("codex", "med")],
    "review": [("codex", "slow"), ("claude", "slow"), ("gemini", "slow")],
    "fix": [("claude", "med"), ("gemini", "med"), ("codex", "med")],
    "commit": [("claude", "fast"), ("gemini", "fast"), ("codex", "fast")],
    "finalize": [("claude", "med"), ("gemini", "med"), ("codex", "med")],
}
```

---

## Group 2: Database & Agent Availability

- [ ] **Add table schema:** In `db.py`, add `agent_availability` table to `_ensure_tables()`:
  ```sql
  CREATE TABLE IF NOT EXISTS agent_availability (
      agent TEXT PRIMARY KEY,
      available INTEGER DEFAULT 1,
      unavailable_until TEXT,
      reason TEXT
  )
  ```

- [ ] **Implement get_agent_availability():** Query single agent's availability status
  ```python
  async def get_agent_availability(self, agent: str) -> dict[str, Any] | None:
      cursor = await self.conn.execute(
          "SELECT available, unavailable_until, reason FROM agent_availability WHERE agent = ?",
          (agent,)
      )
      row = await cursor.fetchone()
      # Return dict with available, unavailable_until, reason or None if not found
  ```

- [ ] **Implement mark_agent_unavailable():** Insert or update unavailability
  ```python
  async def mark_agent_unavailable(
      self, agent: str, unavailable_until: str, reason: str
  ) -> None:
      await self.conn.execute(
          """INSERT INTO agent_availability (agent, available, unavailable_until, reason)
             VALUES (?, 0, ?, ?)
             ON CONFLICT(agent) DO UPDATE SET
               available = 0, unavailable_until = excluded.unavailable_until, reason = excluded.reason""",
          (agent, unavailable_until, reason)
      )
      await self.conn.commit()
  ```

- [ ] **Implement clear_expired_availability():** Reset agents whose TTL has passed
  ```python
  async def clear_expired_availability(self) -> None:
      now = datetime.now(timezone.utc).isoformat()
      await self.conn.execute(
          """UPDATE agent_availability
             SET available = 1, unavailable_until = NULL, reason = NULL
             WHERE unavailable_until IS NOT NULL AND unavailable_until < ?""",
          (now,)
      )
      await self.conn.commit()
  ```

---

## Group 3: Shared Helper Functions

- [ ] **Implement resolve_slug():**
  ```python
  def resolve_slug(cwd: str, slug: str | None) -> str | None:
      """
      If slug provided, return it.
      Otherwise parse todos/roadmap.md:
      1. Find first line with [>] (in-progress) - extract slug
      2. If none, find first [ ] (pending) - extract slug, mark as [>]
      3. Return slug or None if roadmap empty

      Slug extraction: line format is "### [>] slug-name - Description"
      """
  ```

- [ ] **Implement get_available_agent():**
  ```python
  async def get_available_agent(
      db: Database, task_type: str, fallback_matrix: dict[str, list[tuple[str, str]]]
  ) -> tuple[str, str]:
      """
      1. Get fallback list for task_type
      2. Clear expired availability first
      3. For each (agent, thinking_mode) in list:
         - Query availability
         - If available or not in table: return it
      4. If all unavailable: return the one with soonest unavailable_until
      """
  ```

- [ ] **Implement check_file_exists():**
  ```python
  def check_file_exists(cwd: str, relative_path: str) -> bool:
      return (Path(cwd) / relative_path).exists()
  ```

- [ ] **Implement get_archive_path():**
  ```python
  def get_archive_path(cwd: str, slug: str) -> str | None:
      """
      Check if done/*-{slug}/ directory exists.
      Returns the archive path (e.g., "done/005-my-slug") if found, None otherwise.
      """
      done_dir = Path(cwd) / "done"
      if not done_dir.exists():
          return None
      for entry in done_dir.iterdir():
          if entry.is_dir() and entry.name.endswith(f"-{slug}"):
              return f"done/{entry.name}"
      return None
  ```

- [ ] **Implement parse_impl_plan_done():**
  ```python
  def parse_impl_plan_done(cwd: str, slug: str) -> bool:
      """
      Read todos/{slug}/implementation-plan.md
      Parse sections: find "## Group 1" through "## Group 4"
      Within those sections, check for unchecked items: "- [ ]"
      Return True if NO unchecked items in Groups 1-4, False otherwise
      """
  ```

- [ ] **Implement check_review_status():**
  ```python
  def check_review_status(cwd: str, slug: str) -> str:
      """
      Check todos/{slug}/review-findings.md
      Returns:
        - "missing" if file doesn't exist
        - "approved" if contains "[x] APPROVE"
        - "changes_requested" otherwise
      """
  ```

- [ ] **Implement response builders (return plain text, not JSON):**
  ```python
  def format_tool_call(
      command: str, args: str, project: str, agent: str,
      thinking_mode: str, subfolder: str, note: str = ""
  ) -> str:
      """Format a literal tool call for the orchestrator to execute."""
      result = f"""TOOL_CALL:
teleclaude__run_agent_command(
  computer="local",
  command="{command}",
  args="{args}",
  project="{project}",
  agent="{agent}",
  thinking_mode="{thinking_mode}",
  subfolder="{subfolder}"
)"""
      if note:
          result += f"\n\nNOTE: {note}"
      return result

  def format_error(code: str, message: str) -> str:
      return f"ERROR: {code}\n{message}"

  def format_prepared(slug: str) -> str:
      return f"""PREPARED:
todos/{slug} is ready for work.
Run teleclaude__next_work() to start the build/review cycle."""

  def format_complete(slug: str, archive_path: str) -> str:
      return f"""COMPLETE:
todos/{slug} has been finalized.
Delivered to {archive_path}/"""
  ```

---

## Group 4: Git Operations

- [ ] **Implement has_uncommitted_changes():**
  ```python
  def has_uncommitted_changes(repo: Repo, worktree_path: str) -> bool:
      """
      Check if worktree has uncommitted changes (staged or unstaged).
      Use repo.is_dirty(path=worktree_path) or check status.
      """
  ```

- [ ] **Implement ensure_worktree():**
  ```python
  def ensure_worktree(repo: Repo, cwd: str, slug: str) -> None:
      """
      Check if trees/{slug} exists.
      If not, create: git worktree add trees/{slug} -b {slug}
      GitPython: repo.git.worktree('add', f'trees/{slug}', '-b', slug)
      """
  ```

NOTE: `finalize` is NOT automated - it's dispatched to /next-finalize worker.
Merge conflicts, push failures, and network issues need AI judgment to resolve.
The `get_archive_path()` helper (Group 3) detects when finalize completed.

---

## Group 5: Main Functions

- [ ] **Implement next_prepare():**
  ```python
  async def next_prepare(
      db: Database, slug: str | None, cwd: str
  ) -> str:
      """
      Phase A state machine. Returns plain text for orchestrator to execute.

      1. slug = resolve_slug(cwd, slug)
         if not slug: return format_error("NO_WORK", "No pending items in roadmap.")

      2. if not check_file_exists(cwd, f"todos/{slug}/requirements.md"):
            agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
            return format_tool_call(
                command="next-prepare",
                args=slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder="",
                note="Engage as collaborator - this is an architect session requiring discussion."
            )

      3. if not check_file_exists(cwd, f"todos/{slug}/implementation-plan.md"):
            agent, mode = await get_available_agent(db, "prepare", PREPARE_FALLBACK)
            return format_tool_call(
                command="next-prepare",
                args=slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder="",
                note="Engage as collaborator - this is an architect session requiring discussion."
            )

      4. return format_prepared(slug)
      """
  ```

- [ ] **Implement next_work():**
  ```python
  async def next_work(
      db: Database, slug: str | None, cwd: str
  ) -> str:
      """
      Phase B state machine. Returns plain text for orchestrator to execute.

      1. slug = resolve_slug(cwd, slug)
         if not slug: return format_error("NO_WORK", "No pending items in roadmap.")

      2. Check if already finalized (done/*-{slug}/ exists)
         archive_path = get_archive_path(cwd, slug)  # Returns path if exists, None otherwise
         if archive_path: return format_complete(slug, archive_path)

      3. if not (check_file_exists(cwd, f"todos/{slug}/requirements.md") and
                 check_file_exists(cwd, f"todos/{slug}/implementation-plan.md")):
            return format_error("NOT_PREPARED",
                f"todos/{slug} is missing requirements or implementation plan.\n"
                f"Run teleclaude__next_prepare(\"{slug}\") first.")

      4. repo = Repo(cwd)
         ensure_worktree(repo, cwd, slug)

      5. worktree_path = f"{cwd}/trees/{slug}"
         if has_uncommitted_changes(repo, worktree_path):
            agent, mode = await get_available_agent(db, "commit", WORK_FALLBACK)
            return format_tool_call(
                command="commit-pending",
                args=slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder=f"trees/{slug}"
            )

      6. if not parse_impl_plan_done(cwd, slug):
            agent, mode = await get_available_agent(db, "build", WORK_FALLBACK)
            return format_tool_call(
                command="next-build",
                args=slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder=f"trees/{slug}"
            )

      7. review_status = check_review_status(cwd, slug)
         if review_status == "missing":
            agent, mode = await get_available_agent(db, "review", WORK_FALLBACK)
            return format_tool_call(
                command="next-review",
                args=slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder=f"trees/{slug}"
            )

      8. if review_status == "changes_requested":
            agent, mode = await get_available_agent(db, "fix", WORK_FALLBACK)
            return format_tool_call(
                command="next-fix-review",
                args=slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder=f"trees/{slug}"
            )

      9. Review approved - dispatch finalize worker (runs from MAIN REPO, not worktree)
         agent, mode = await get_available_agent(db, "finalize", WORK_FALLBACK)
         return format_tool_call(
             command="next-finalize",
             args=slug,
             project=cwd,
             agent=agent,
             thinking_mode=mode,
             subfolder=""  # Empty = main repo, NOT worktree
         )

      (complete is returned on next call when step 2 finds archive_path)
      """
  ```

---

## Group 6: MCP Tools & Wrapper

- [ ] **Implement teleclaude__next_prepare MCP tool:**
  ```python
  @mcp.tool()
  async def teleclaude__next_prepare(
      slug: str | None = None,
      cwd: str | None = None,
  ) -> str:
      """
      Phase A: Prepare work items by discovering requirements and creating implementation plans.
      Returns plain text instructions for the orchestrator to execute.
      """
      if not cwd:
          return "ERROR: NO_CWD\nWorking directory not provided. This should be auto-injected by MCP wrapper."
      db = get_database()
      return await next_prepare(db, slug, cwd)
  ```

- [ ] **Implement teleclaude__next_work MCP tool:**
  ```python
  @mcp.tool()
  async def teleclaude__next_work(
      slug: str | None = None,
      cwd: str | None = None,
  ) -> str:
      """
      Phase B: Execute build/review/fix cycle on prepared work items.
      Returns plain text instructions for the orchestrator to execute.
      """
      if not cwd:
          return "ERROR: NO_CWD\nWorking directory not provided. This should be auto-injected by MCP wrapper."
      db = get_database()
      return await next_work(db, slug, cwd)
  ```

- [ ] **Implement teleclaude__mark_agent_unavailable MCP tool:**
  ```python
  @mcp.tool()
  async def teleclaude__mark_agent_unavailable(
      agent: str,
      unavailable_until: str,
      reason: str,
  ) -> str:
      """
      Mark an agent as unavailable until the specified time.
      Called by orchestrator when a dispatch fails due to rate limits or outages.
      """
      db = get_database()
      await db.mark_agent_unavailable(agent, unavailable_until, reason)
      return f"OK: {agent} marked unavailable until {unavailable_until} ({reason})"
  ```

- [ ] **Update MCP wrapper for cwd injection:**
  In `bin/mcp-wrapper.py`, update `CONTEXT_TO_INJECT` and injection logic:
  ```python
  # Special handling for cwd - use os.getcwd() instead of env var
  CONTEXT_TO_INJECT: dict[str, str | None] = {
      "caller_session_id": "TELECLAUDE_SESSION_ID",
      "cwd": None,  # Special marker for getcwd()
  }

  # In injection logic:
  if value is None and key == "cwd":
      params[key] = os.getcwd()
  ```

---

## Group 7: Architect Command

- [ ] **Create /next-prepare command:** `~/.agents/commands/next-prepare.md`
  - Check what's missing for todos/{slug}:
    - If no requirements.md: discover requirements collaboratively
    - If no implementation-plan.md: create plan collaboratively
  - Engage with orchestrator as sparring partner
  - Write the missing file(s)
  - Commit the file(s)

---

## Group 8: Builder Commands

- [ ] **Create /commit-pending command:** `~/.agents/commands/commit-pending.md`
  - Check git status
  - Analyze changes to craft appropriate commit message
  - Commit with proper format

- [ ] **Create /next-fix-review command:** `~/.agents/commands/next-fix-review.md`
  - Read `todos/{slug}/review-findings.md`
  - Read `todos/{slug}/requirements.md`
  - For each issue in Critical/Important sections: make fix, run tests
  - Delete `todos/{slug}/review-findings.md`
  - Commit all changes

- [ ] **Update /next-build command:** Ensure it commits after each task completion

- [ ] **Update /next-review command:** Ensure verdict format is exactly `[x] APPROVE` or `[x] REQUEST CHANGES`

---

## Group 9: Orchestrator Behavior (No separate commands needed)

The orchestrator is any AI that calls the MCP tools and executes the returned instructions.
No separate "orchestrator commands" are needed - the tools return literal instructions.

**Prepare flow:**
1. AI calls `teleclaude__next_prepare()`
2. Tool returns `TOOL_CALL: teleclaude__run_agent_command(command="next-prepare", ...)`
3. AI executes that tool call (starts architect session)
4. AI engages as collaborator with the architect
5. When architect completes, AI calls `teleclaude__next_prepare()` again
6. Repeat until `PREPARED:` is returned

**Work flow:**
1. AI calls `teleclaude__next_work()`
2. Tool returns `TOOL_CALL: teleclaude__run_agent_command(command="next-build", ...)`
3. AI executes that tool call (starts worker session)
4. AI waits for worker completion
5. AI calls `teleclaude__next_work()` again
6. Repeat until `COMPLETE:` is returned

---

## Group 10: Testing

- [ ] **Unit tests for shared helpers:**
  - `test_resolve_slug_from_argument`
  - `test_resolve_slug_from_roadmap_in_progress`
  - `test_resolve_slug_from_roadmap_pending`
  - `test_resolve_slug_empty_roadmap`
  - `test_parse_impl_plan_done_all_checked`
  - `test_parse_impl_plan_done_has_unchecked`
  - `test_check_review_status_missing`
  - `test_check_review_status_approved`
  - `test_check_review_status_changes_requested`

- [ ] **Unit tests for agent availability:**
  - `test_get_available_agent_first_available`
  - `test_get_available_agent_fallback`
  - `test_get_available_agent_expired_ttl`
  - `test_mark_agent_unavailable`
  - `test_clear_expired_availability`

- [ ] **Integration tests for main functions:**
  - `test_next_prepare_no_work`
  - `test_next_prepare_needs_requirements`
  - `test_next_prepare_needs_plan`
  - `test_next_prepare_prepared`
  - `test_next_work_not_prepared`
  - `test_next_work_needs_build`
  - `test_next_work_needs_review`
  - `test_next_work_needs_fix`
  - `test_next_work_complete`

---

## Group 11: Review & Polish

- [ ] **Review:** Verify all requirements met
- [ ] **Codex review:** Use /next-review for thorough code review
- [ ] **Documentation:** Update AGENTS.md with new workflow commands
