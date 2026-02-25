# DOR Report: mcp-migration-delete-mcp

## Gate Verdict: PASS — Score 9/10

Assessed by: Architect (gate mode)
Date: 2026-02-22

---

### Gate 1: Intent & Success — PASS

- Problem statement is explicit: delete all MCP server code and update docs.
- Success criteria in requirements.md are concrete and grep-verifiable (11 items).
- The "what" and "why" are clear: Phase 3 cleanup after Phases 1+2 migrated consumers.

### Gate 2: Scope & Size — PASS

- Estimated ~3,400 lines of pure deletion + reference cleanup in ~25 files.
- Two-commit structure (code, docs) keeps each commit atomic.
- Cross-cutting nature is inherent to deletion but well-bounded by file lists.
- Fits single AI session — deletion is mechanically straightforward.

### Gate 3: Verification — PASS

- Verification is grep-based: no `*mcp*` files, no MCP imports, no `teleclaude.sock` refs.
- `make lint` + `make test` as quality gates.
- Daemon startup without MCP as integration check.
- Demo.md provides concrete, copy-paste-ready validation commands.

### Gate 4: Approach Known — PASS

- Approach is proven: file deletion + reference cleanup + grep verification.
- **Decision point resolved:** The `--allowed-mcp-server-names _none_` hardcoded in
  Gemini's flags string is a native Gemini CLI flag — it stays. The `mcp_tools_arg`
  field, `mcp_tools` parameter, and `--mcp-tools` CLI argument are TeleClaude's
  dynamic wrapper infrastructure — those get deleted. Verified by inspecting
  `agent_cli.py` (lines 102, 110) and the Phase 2 plan (which adds the flag to
  profiles, not the dynamic machinery). No remaining unknowns.

### Gate 5: Research Complete — PASS (auto-satisfied)

- No third-party tools introduced. Pure deletion task.

### Gate 6: Dependencies & Preconditions — PASS

- Dependency on `mcp-migration-agent-config` is explicit in requirements.md and roadmap.
- Phase 2 state: `pending` — this is correct; Phase 3 cannot start until Phase 2 completes.
- No external system dependencies.

### Gate 7: Integration Safety — PASS

- Single atomic commit for code deletion enables clean `git revert` if needed.
- Separate commit for docs avoids coupling code and doc changes.
- Binary outcome: MCP is fully removed or it is not. No partial states.

### Gate 8: Tooling Impact — PASS (auto-satisfied)

- No tooling/scaffolding changes. Pure deletion.

---

## Plan-to-Requirement Fidelity

Checked every implementation plan task against requirements.md:

| Plan Task                          | Requirement Trace                                                                                              | Status  |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------- |
| 1.1: Delete MCP server files       | "Delete `teleclaude/mcp_server.py`", "Delete `teleclaude/mcp/` directory", "Delete `bin/mcp-wrapper.py`", etc. | Aligned |
| 1.2: Remove from daemon startup    | "Remove MCP server initialization from daemon startup"                                                         | Aligned |
| 1.3: Remove constants              | "Clean up MCP-related constants in `teleclaude/constants.py`"                                                  | Aligned |
| 1.4: Remove origin/model methods   | Implied by "No MCP imports in any Python file" + file deletion                                                 | Aligned |
| 1.5: Remove adapter infrastructure | Implied by "No MCP imports in any Python file"                                                                 | Aligned |
| 1.6: Remove from services          | Implied by comprehensive MCP removal                                                                           | Aligned |
| 1.7: Clean up agent CLI refs       | "Remove `.state.json` MCP tools tracking", MCP removal from code                                               | Aligned |
| 1.8: Clean up incidental refs      | "No reference to `teleclaude.sock`", "No MCP imports"                                                          | Aligned |
| 1.9: Update pyproject.toml         | "Remove `mcp` package from pyproject.toml", "Run `uv lock`"                                                    | Aligned |
| 1.10: Verify code commit           | Success criteria verification                                                                                  | Aligned |
| 2.1-2.6: Doc cleanup               | All doc items from requirements "Documentation cleanup" section                                                | Aligned |

**Contradictions found:** None. Requirements say "no behavioral changes — this is deletion
and doc cleanup." The plan prescribes only deletion, reference cleanup, and doc updates.
No behavioral changes introduced.

**Coverage gap:** None. Every requirement item has at least one plan task covering it.

## Resolved Questions

1. **`--allowed-mcp-server-names` retention:** Resolved. The hardcoded flag in Gemini's
   flags string stays (native CLI flag). TeleClaude's `mcp_tools_arg`/`mcp_tools`
   dynamic wrapper machinery gets deleted. Implementation plan updated with resolution.

2. **`docs/third-party/a2a-protocol/mcp-integration.md`:** Reviewed content. This doc
   describes the general A2A/MCP protocol relationship (external concepts, not
   TeleClaude's MCP server). Task 2.4 correctly instructs the builder to review and
   decide keep/delete. Recommendation: keep — it is reference material about external
   protocols.

## Verified Assumptions

- `from_mcp` class methods in `models.py` are only called from `mcp_server.py`
  (confirmed via grep — only 2 files contain `from_mcp`, both targeted for deletion).
- `InputOrigin.MCP` exists in `origins.py` and is referenced in `identity.py` —
  both covered by Task 1.4.

## Score Rationale

Previous draft scored 7 with one blocker (the `--allowed-mcp-server-names` decision).
That blocker is now resolved with evidence. All 8 gates pass cleanly. Score: 9/10.
The 1-point deduction reflects that Phase 2 dependency is still pending (correct
sequencing, but the builder cannot start until it delivers).
