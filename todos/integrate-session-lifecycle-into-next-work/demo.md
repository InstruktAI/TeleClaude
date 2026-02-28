# Demo: integrate-session-lifecycle-into-next-work

## Validation

```bash
# Verify the verify-artifacts CLI command exists and accepts --help
telec todo verify-artifacts --help
```

```bash
# Verify next-work command includes session-lifecycle in required reads
grep -q "session-lifecycle" agents/commands/next-work.md && echo "PASS: session-lifecycle in required reads" || echo "FAIL"
```

```bash
# Run artifact verification against a known todo slug (should exit 0 or 1 cleanly)
telec todo verify-artifacts integrate-session-lifecycle-into-next-work --phase build --cwd "$(pwd)" || true
```

```bash
# Verify POST_COMPLETION contains direct conversation pattern
grep -q "direct" teleclaude/core/next_machine/core.py && echo "PASS: direct conversation in POST_COMPLETION" || echo "FAIL"
```

```bash
# Run tests for the new verify_artifacts function
make test PYTEST_ARGS="-k test_next_machine_verify_artifacts"
```

## Guided Presentation

### Step 1: Artifact Verification Gate

Run `telec todo verify-artifacts <slug> --phase build` against a completed build. Observe the structured report listing each check (implementation plan checkboxes, commit presence, quality checklist). The command exits 0 when all checks pass, non-zero with a clear report when they don't. This replaces manual AI verification of artifact completeness.

### Step 2: Direct Peer Conversation Flow

Trigger a review that returns REQUEST CHANGES. Observe that the orchestrator:

1. Does NOT end the reviewer session
2. Dispatches a fixer worker
3. Establishes `--direct` links between reviewer and fixer
4. The fixer and reviewer iterate together — the reviewer provides inline feedback, the fixer addresses it
5. When the reviewer approves, the orchestrator reads the verdict, ends both sessions, and continues

This eliminates the context-destroying churn of: end reviewer → dispatch fixer → end fixer → dispatch new reviewer.

### Step 3: Session Lifecycle Discipline

View `agents/commands/next-work.md` and confirm `session-lifecycle` is in required reads. Run a full build-review cycle and observe:

- Clean session list: only working sessions are visible
- Orchestrator ends all children after processing results
- Artifact delivery is verified before session cleanup
- No orphaned sessions remain after the cycle completes
