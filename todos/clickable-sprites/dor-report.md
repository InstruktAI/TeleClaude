# DOR Report: clickable-sprites

## Gate Assessment Date
2026-03-06 (gate phase)

## Gate Verdict: PASS (8/10)

All eight DOR gates satisfied. Artifacts are grounded in verified codebase evidence.
Ready for implementation.

---

## Gate Results

### 1. Intent & Success — PASS
Problem and outcome are explicit. Requirements define 6 concrete, testable success criteria
(visible error messages, daemon-free startup, source URLs populated, browser opens on click,
contributor flow works). The "what" and "why" are captured in both `input.md` and `requirements.md`.

### 2. Scope & Size — PASS (tight)
11 tasks across 3 phases. Phase 1 (resilience) includes 3 tasks tangentially related to
"clickable sprites" — justified as contributor-friendliness prerequisites. Each task is
narrowly scoped to specific files. The work fits a single session: Phase 1 is defensive
wrapping, Phase 2 is additive field/method additions, Phase 3 is docs/tests.

### 3. Verification — PASS
Each requirement has a verification path:
- Sprite validation: unit test with malformed sprite + stderr output check.
- Daemon-free startup: manual or integration test (TUI renders without daemon).
- Logging resilience: test with absent log directory.
- Source URLs: unit test for field existence and population on all sprites.
- Click handling: unit test for `hit_test()` + manual TUI click verification.
- Contributor flow: manual walkthrough of CONTRIBUTING.md.

Demo artifact (`demo.md`) provides executable validation scripts and a guided presentation.

### 4. Approach Known — PASS
All technical paths verified against codebase:
- **Frozen dataclasses**: `CompositeSprite` (`composite.py:27`), `AnimatedSprite` (`composite.py:85`),
  `SpriteGroup` (`composite.py:115`) — confirmed `@dataclass(frozen=True)`. Adding optional
  `source_url` field with default is standard.
- **`resolve_colors()` copy**: `composite.py:58-78` constructs a new `CompositeSprite` passing
  all fields — `source_url` must be added to this constructor call. Plan correctly notes this.
- **Error isolation pattern**: analogous to existing try/except in animation engine.
- **`on_click` handler**: pattern used in 12+ widgets (`session_row.py:287`, `todo_row.py:210`,
  `status_bar.py:176`, etc.).
- **`webbrowser.open()`**: stdlib, no dependencies.
- **`_show_animation_toast`**: confirmed no-op at `app.py:1177` (empty method body).
- **Entity bounding boxes**: `GlobalSky.update()` computes `ex`, `ey`, `sprite_w` per entity
  (`general.py:350-378`). Tracking bounds is straightforward.

**Builder note**: The `AnimationEngine` does not currently expose a reference to `GlobalSky`.
Task 2.4 requires wiring: either add a property on the engine or pass the sky reference to
Banner. Implementation plan updated to note this.

### 5. Research Complete — PASS (no external dependencies)
No third-party libraries. `webbrowser` is stdlib. Textual mouse events (`Click`) are used
extensively in the existing widget codebase.

### 6. Dependencies & Preconditions — PASS
No blocking dependencies in `roadmap.yaml`. All prerequisite code exists:
- `CompositeSprite`/`AnimatedSprite` dataclasses in `composite.py`.
- `get_sky_entities()` auto-discovery in `__init__.py`.
- `GlobalSky` entity rendering in `general.py`.
- `Banner` widget rendering in `banner.py`.
- `_scan_sky_entity()` Z-buffer scanning already implemented.

### 7. Integration Safety — PASS
All changes are additive and backward-compatible:
- `source_url` is optional with default `None` — no existing code breaks.
- Sprite validation wraps existing iteration in per-sprite try/except — valid sprites unaffected.
- Click handler is a new method on Banner — no existing rendering behavior changes.
- Logging fallback activates only when directory is missing — normal operation unaffected.

### 8. Tooling Impact — NOT APPLICABLE
No tooling or scaffolding changes.

---

## Plan-to-Requirement Fidelity

| Requirement | Plan Task(s) | Status |
|---|---|---|
| R1: Sprite validation errors | 1.1 | Traced |
| R2: Graceful daemon-free startup | 1.2 | Traced |
| SC3: Logging resilience | 1.3 | Traced |
| R3: Source URL metadata | 2.1, 2.2 | Traced |
| R4: Clickable sprite area | 2.3, 2.4, 2.5 | Traced |
| R5: Authoring instructions | 3.1 | Traced |
| Verification | 3.2, 3.3 | Traced |

No contradictions found between plan and requirements. Plan adds `source_url` to `SpriteGroup`
(beyond requirements' scope of `CompositeSprite` and `AnimatedSprite`) — harmless extra but
builder should prioritize the two required dataclasses.

## Assumptions (Inferred — builder should verify)

1. **Sprite origins**: All current sprites assumed authored in this repo. Builder should
   verify during Task 2.2 and use external URLs if any were adapted from other sources.

2. **`instrukt_ai_logging` behavior**: Assumed `configure_logging()` raises when log
   directory is absent. Builder verifies empirically in Task 1.3.

3. **Banner coordinate mapping**: Screen x in Banner rendering (`for x in range(total_width)`)
   maps 1:1 to GlobalSky's internal coordinate system. Verified: Banner iterates the same
   x range used by GlobalSky. Compact mode uses different letter mapping but same x space.

## Open Questions

None — remaining details are implementation-level and resolvable by the builder through
empirical verification during build.
