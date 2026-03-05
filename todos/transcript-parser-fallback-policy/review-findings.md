# Review Findings: transcript-parser-fallback-policy

## Verdict: APPROVE

## Requirements Tracing

All success criteria from `requirements.md` are satisfied:

| Requirement | Status | Evidence |
|---|---|---|
| `resolve_parser_agent(active_agent: str \| None) -> AgentName` exists in `teleclaude/core/agents.py` | Met | `agents.py:39-55` |
| All four callsites use centralized function | Met | `streaming.py:121` and `api_server.py:1097` updated; tasks 1.4/1.5 verified enum-typed callers need no change |
| Debug log for None/empty, warning for unknown | Met | `agents.py:46` (debug), `agents.py:51-54` (warning) |
| Fallback resolves to `AgentName.CLAUDE` | Met | Both return paths yield `AgentName.CLAUDE` |
| Unit tests cover all specified cases | Met | 7 tests in `test_agents.py:213-258` |
| No existing tests break | Met | Builder notes 2830 passed; 4 pre-existing failures fixed in separate commit |

## Paradigm-Fit Assessment

- **Data flow**: Uses existing `AgentName` enum and `from_str()` — no bypass.
- **Component reuse**: `resolve_parser_agent` composes `AgentName.from_str()` rather than reimplementing resolution.
- **Pattern consistency**: Module logger (`logging.getLogger(__name__)`) matches project convention. Function placement in `teleclaude/core/agents.py` is the natural home for agent-related resolution logic.

No paradigm violations.

## Principle Violation Hunt

### 1. Fallback & Silent Degradation

The `resolve_parser_agent` function IS the codified fallback policy — this is the requirement itself. The fallback to `AgentName.CLAUDE` is justified by backward compatibility for historical transcript rendering (documented in requirements and docstring). The exception catch is narrow (`ValueError` only from `from_str`), not a broad catch. Logging differentiates expected (debug) from unexpected (warning) cases. **No unjustified fallbacks.**

### 2. Fail Fast

The function validates at the boundary (raw string input) and returns a typed enum. Callers downstream operate on `AgentName` enum values — trusted code. Correct boundary placement.

### 3. DIP

Core function in `teleclaude/core/agents.py`. API layer imports from core. Dependency direction is correct.

### 4. Coupling & Law of Demeter

No multi-dot chains. `session.active_agent` is a single attribute access at the callsite.

### 5. SRP

`resolve_parser_agent` does one thing: resolve a raw string to AgentName with fallback. Clean.

### 6. YAGNI / KISS

Minimal implementation: one function, two callsite updates, two verification tasks. No over-engineering.

### 7. Encapsulation / Immutability

Pure function (side effects limited to logging). No mutation.

## Test Quality

- 7 tests covering: canonical values (parametrized), None, empty, unknown, case-insensitive, warning log, debug log
- All tests verify behavior, not implementation details
- Log assertions check observable output (level + message content)
- No prose-lock assertions

## Demo Review

- 3 executable bash blocks: import check, assertion-based validation, pytest run
- All commands, imports, and assertions correspond to real implemented code
- Guided presentation references actual files and behavior
- No fabricated output

## Logging Hygiene

- Uses `logging.getLogger(__name__)` — structured, project-standard
- No debug probes or print statements

## Critical

_(none)_

## Important

_(none)_

## Suggestions

- **Unrelated test fixes on feature branch**: 4 test files (`test_integrator_wiring.py`, `test_next_machine_hitl.py`, `test_next_machine_state_deps.py`, `test_tab_bar_edge.py`) contain assertion updates unrelated to this slug. They're in a separate commit (`edc8d593c`) and fix pre-existing stale assertions. Cleanly separated, but adds noise to the review diff. Consider landing unrelated test fixes on main independently in the future.

## Why No Issues

1. **Paradigm-fit verified**: Resolution function uses existing `AgentName.from_str()` enum pattern; callsite migrations follow existing import conventions; module logger placement is standard.
2. **Requirements validated**: All 6 success criteria traced to specific code locations (see table above). Each callsite was individually verified.
3. **Copy-paste duplication checked**: The two updated callsites previously had duplicated inline try/except blocks — this delivery eliminates that duplication by centralizing into `resolve_parser_agent`. No new duplication introduced.
4. **Fallback justification reviewed**: The fallback to Claude is the explicit, documented requirement (backward compatibility for historical transcripts). Logging differentiates expected vs. unexpected cases — this is the gold standard for justified fallback behavior.
