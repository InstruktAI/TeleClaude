---
id: 'project/spec/feature/integration/agent-stop-checkpoint-blocking'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Heuristic checkpoint engine that may block an agent_stop hook with an adapter-formatted instruction nudging the agent to commit, run tests, fix lint, or address uncommitted work.'
---

# Agent Stop Checkpoint Blocking — Spec

## Required reads

- @~/.teleclaude/docs/software-development/principle/domain-driven-design.md
- @~/.teleclaude/docs/software-development/spec/domain-spec.md
- @docs/project/spec/domain/integration.md

## What it is

A deterministic, zero-LLM heuristic engine invoked from the hook receiver on
`agent_stop` events. It reads the current turn's transcript, the working
tree's git state scoped to the turn window, and a session's project context,
then classifies changed files into categories (code, tests, docs, configs,
infra) and produces a `CheckpointResult` listing required actions. If any
actions are required, the receiver emits an adapter-formatted block JSON to
stdout that causes the agent CLI to re-prompt itself with the checkpoint
instruction.

The engine is gated by session-scoped flag files: a persistent **clear flag**
disables checkpoints for the session entirely; turn scoping prevents ordinary
file-change checkpoints from re-firing after a checkpoint has been delivered;
and a SHA-scoped **post-commit review flag** prevents the main-branch
post-commit review action from re-firing for the same HEAD.

## Canonical fields

### Use cases

#### UC-CP1: Uncommitted code changes block stop

```gherkin
Given a Claude session has modified Python files in the current turn
And no commit has been recorded since the last mutation
And the persistent clear flag is not set
When Claude invokes telec-hook ... Stop
Then _maybe_checkpoint_output loads the session row
And resolves project_path (falling back to transcript-derived workdir, adjusted for worktree subdir)
And _resolve_turn_start returns max(last_message_sent_at, last_checkpoint_at)
And get_checkpoint_content runs the heuristic engine
And the engine reports code category present + commit_action_required true
And build_checkpoint_message composes a CHECKPOINT_PREFIX-prefixed instruction listing required actions
And enqueue_checkpoint_seen records a CHECKPOINT_SEEN outbox row at checkpoint_at = now
And ClaudeAdapter.format_checkpoint_response serializes {"decision":"block","reason":<message>}
And the receiver prints the JSON and exits 0 BEFORE enqueueing the AGENT_STOP row
```

#### UC-CP2: Persistent clear flag skips checkpoint

```gherkin
Given is_checkpoint_disabled(session_id) returns True because the session-scoped CHECKPOINT_CLEAR_FLAG file exists
When _maybe_checkpoint_output runs
Then the CHECKPOINT_RECHECK_FLAG is consumed (cleared) so a future enable can re-arm checkpoints cleanly
And an "Checkpoint skipped (persistent clear flag)" info log emits
And _maybe_checkpoint_output returns None
And the receiver enqueues the AGENT_STOP row normally without emitting a block response
```

#### UC-CP3: No turn start → no checkpoint

```gherkin
Given the session row has neither last_message_sent_at nor last_checkpoint_at set
When _resolve_turn_start returns None
Then _maybe_checkpoint_output logs "Checkpoint skipped (no turn start)" at debug
And returns None
And the receiver proceeds to enqueue the AGENT_STOP row
```

#### UC-CP4: No turn-local changes → no checkpoint

```gherkin
Given get_checkpoint_content returns an empty string (engine found no required actions)
When _maybe_checkpoint_output runs
Then a debug log records "Checkpoint skipped: no turn-local changes"
And returns None
And no CHECKPOINT_SEEN row is enqueued
And the AGENT_STOP event enqueues normally
```

#### UC-CP5: Per-turn recheck flag cleared on new user prompt

```gherkin
Given a checkpoint fired earlier in this turn and set CHECKPOINT_RECHECK_FLAG
When a new user_prompt_submit hook arrives that is NOT system-injected
Then _reset_checkpoint_flags consumes CHECKPOINT_RECHECK_FLAG
And the next agent_stop in the new turn may fire a fresh checkpoint
```

#### UC-CP5A: Main-branch post-commit review action is edge-triggered per HEAD

```gherkin
Given the current branch is main
And the current HEAD differs from the turn-start anchor SHA
And no post-commit review flag exists for the current HEAD
When get_checkpoint_content runs
Then the heuristic engine includes the post-commit review-gate surfacing action
And that action instructs the agent to set a non-blocking 5-minute heartbeat when it recommends review
And if that heartbeat fires without a user response approving or declining review, the agent dispatches the commit(s) to review
And waits for REVIEW COMPLETE before reporting completion
And records a post-commit review flag for the current HEAD under the session flag directory
And removes older post-commit review flags for the same session

Given the current branch is main
And the current HEAD differs from the turn-start anchor SHA
And a post-commit review flag already exists for the current HEAD
And there are no turn-local dirty files
When get_checkpoint_content runs again before a new commit
Then it returns None
And does not emit the post-commit review-gate surfacing action again

Given the current branch is main
And the current HEAD differs from the turn-start anchor SHA
And a post-commit review flag already exists for the current HEAD
And there are turn-local dirty files
When get_checkpoint_content runs
Then ordinary checkpoint classification still runs for those files
And only the post-commit review-gate surfacing action is suppressed
```

#### UC-CP6: Per-adapter checkpoint response payloads

```gherkin
Given args.agent is one of "claude", "codex", or "gemini"
And each adapter sets supports_hook_checkpoint = True in v1
When _maybe_emit_checkpoint_response runs and a non-empty checkpoint_reason is returned
Then adapter.format_checkpoint_response(checkpoint_reason) emits:
    - Claude → json.dumps({"decision": "block", "reason": <reason>})
    - Codex  → json.dumps({"decision": "block", "reason": <reason>})
    - Gemini → json.dumps({"decision": "deny",  "reason": <reason>})
And the receiver prints the JSON to stdout and exits 0 BEFORE enqueueing the AGENT_STOP row

Given a hypothetical adapter that sets supports_hook_checkpoint = False
When _maybe_emit_checkpoint_response evaluates the early-return guard
Then it short-circuits before the heuristic engine runs and the AGENT_STOP row enqueues normally
(No v1 adapter takes this branch.)
```

#### UC-CP7: Heuristic engine fail-open returns CHECKPOINT_MESSAGE fallback

```gherkin
Given the heuristic engine inside get_checkpoint_content hits an internal failure (transcript IO error, git error, evidence-gathering exception)
When the engine's outer try/except catches the exception
Then get_checkpoint_content returns the CHECKPOINT_MESSAGE constant (fail-open fallback) — NOT None
And _maybe_checkpoint_output treats CHECKPOINT_MESSAGE as a non-empty reason
And enqueue_checkpoint_seen records a CHECKPOINT_SEEN outbox row at now
And adapter.format_checkpoint_response(CHECKPOINT_MESSAGE) emits the block payload
And the receiver prints the JSON and exits 0
And the AGENT_STOP row is NOT enqueued (the receiver exited before reaching enqueue_hook_event)

Given _maybe_checkpoint_output ITSELF raises (AttributeError, TypeError, ValueError, SQLAlchemyError) OUTSIDE the engine's try/except
When _maybe_emit_checkpoint_response catches it
Then a warning log "Checkpoint eval crashed (ignored)" is emitted
And no block response is printed
And the receiver proceeds to enqueue the AGENT_STOP event normally
This second branch covers unexpected failures that escape _maybe_checkpoint_output.
It does NOT cover _load_checkpoint_row SQLAlchemyError: _load_checkpoint_row catches that locally, logs "Checkpoint eval skipped (db error)" at debug, returns None, and checkpoint evaluation returns no block.
```

#### UC-CP8: Worktree subdir resolution for branch detection

```gherkin
Given the session's subdir starts with "trees/" (it is a worktree session)
When _resolve_checkpoint_project_path runs
Then it composes project_path + subdir into a single working path
And the heuristic engine runs branch detection (_current_branch) against the worktree, not the repo root
```

### Implementation pointers (v1)

- `teleclaude/hooks/receiver/__init__.py` —
  `_maybe_checkpoint_output` (L234),
  `_maybe_emit_checkpoint_response` (L777),
  `_resolve_checkpoint_project_path` (L141),
  `_resolve_turn_start` (L165),
  `_reset_checkpoint_flags` (L228).
- `teleclaude/hooks/checkpoint/__init__.py` —
  `get_checkpoint_content` (L329, top-level entry; fail-open returns
  `CHECKPOINT_MESSAGE`),
  `build_checkpoint_message` (L222),
  `run_heuristics` (L119),
  `_compose_checkpoint_message` (L248),
  `_commit_instruction` (L233).
- `teleclaude/hooks/checkpoint/_evidence.py` — evidence gathering:
  `_has_commit_evidence` (L77),
  `_has_commit_evidence_after_last_mutation` (L111),
  `_has_evidence_after_index` (L139),
  `_check_edit_hygiene` (L747),
  `_check_error_state` (L360),
  `_check_slug_alignment` (L782),
  `_iter_shell_command_records` (L123).
- `teleclaude/hooks/checkpoint/_git.py` —
  `_categorize_files` (L413),
  `_current_branch` (L117),
  `_command_likely_mutates_files` (L173),
  `_extract_apply_patch_paths` (L292),
  `_extract_shell_touched_paths` (L272),
  `_scope_git_files_to_current_turn` (L362),
  `_transcript_observability` (L131).
- `teleclaude/hooks/checkpoint/_models.py` — `CheckpointContext`,
  `CheckpointResult`, `TranscriptObservability` (file ~35 lines).
- `teleclaude/hooks/checkpoint_flags.py` —
  `CHECKPOINT_CLEAR_FLAG` (L17),
  `CHECKPOINT_RECHECK_FLAG` (L18),
  `is_checkpoint_disabled` (L83),
  `set_checkpoint_flag` (L44),
  `has_checkpoint_flag` (L60),
  `consume_checkpoint_flag` (L65),
  `checkpoint_flag_path` (L38).
- `teleclaude/utils/transcript.py` — `TurnTimeline`,
  `extract_effective_tool_calls`, `extract_workdir_from_transcript`.
- `teleclaude/session_scoping.py` — `ScopedPathsResult`,
  `resolve_scoped_paths` for turn-local file attribution.
- `teleclaude/constants.py` — `CHECKPOINT_PREFIX`, `CHECKPOINT_MESSAGE`
  (L230), `CHECKPOINT_LOG_CHECK_EVIDENCE`, `CHECKPOINT_TEST_EVIDENCE`.

### Cross-context references

- Belongs (in v2) to `agent_runtime` along with the receiver, since
  checkpoint blocking is a property of agent-CLI orchestration, not of
  external integration.
- Reads session row state owned by `agent_runtime`:
  `last_message_sent_at`, `last_checkpoint_at`, `native_log_file`,
  `subdir`, `project_path`, `turn_anchor_sha`, `working_slug`,
  `native_session_id`.
- Writes `CHECKPOINT_SEEN` outbox rows that
  `session-state-mutation-via-outbox` handles to update
  `last_checkpoint_at`.

## Known caveats

- Persistent flag files live under the TeleClaude session TMPDIR
  (`TMP_SESSIONS_DIR/<session_id>/<flag_name>`); session ids that contain
  unsafe characters are hashed to a sha256-derived component for the
  filesystem path.
- The CLEAR flag persists across turns until manually removed; it is the
  user/operator's responsibility to delete it to re-enable checkpoints.
- Heuristics are zero-LLM, deterministic pattern matching on git state
  and the transcript — no API calls.
- The engine is project-aware: `_is_checkpoint_project_supported` may
  short-circuit early for projects outside the supported set (the
  engine's project-allowlist policy lives in `_git.py`).
- Worktree-aware path resolution composes `project_path + subdir` so
  branch detection runs against the working tree, not the repo root.
  Worktree sessions on a non-main branch behave correctly; sessions on
  main get the main-only category instructions (setup, deps,
  daemon-restart) suppressed.
- `_resolve_agent_enum` falls back to the default agent if the agent
  string is not a known `AgentName` value — pragmatic guard for unknown
  agents.
- All three v1 adapters set `supports_hook_checkpoint = True`. Claude
  and Codex emit `{"decision": "block", ...}`; Gemini emits
  `{"decision": "deny", ...}`. The shape differences track each agent
  CLI's stdin-protocol for blocking continuations.
- The checkpoint message is prefixed with `CHECKPOINT_PREFIX` so the
  receiver's `_is_teleclaude_system_prompt` filter can drop the echoed
  prompt when the agent re-submits it on the next turn.
