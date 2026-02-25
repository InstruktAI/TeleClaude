# Implementation Plan: consolidate-methodology-skills

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create 6 methodology skills in `agents/skills/` adapted from Claude Code plugin sources, validate with `telec sync`, distribute to all runtimes, and keep the branch's adjacent CLI/runtime/install/test/doc/roadmap behavior contract-aligned with this todo.

**Approach:** Two-track delivery.

1. Artifact authoring for the six methodology skills.
2. Explicit alignment of already-landed branch behavior in:
   - `teleclaude/cli/telec.py`
   - `teleclaude/cli/config_cli.py`
   - `teleclaude/config/runtime_settings.py`
   - `teleclaude/install/install_hooks.py`
   - `teleclaude/invite.py`
   - `tests/*`
   - `tools/test.sh`
   - `docs/project/spec/telec-cli-surface.md`
   - `todos/roadmap.yaml`

No unrelated feature work outside these surfaces.

**Reference pattern:** `agents/skills/research/SKILL.md`, `agents/skills/next-code-reviewer/SKILL.md` — follow their frontmatter and section structure.

**Source locations:**

- Superpowers: `~/.claude/plugins/cache/claude-plugins-official/superpowers/4.3.0/skills/`
- Frontend-design: `~/.claude/plugins/cache/claude-plugins-official/frontend-design/236752ad9ab3/skills/`

---

### Task 1: systematic-debugging

**File(s):** `agents/skills/systematic-debugging/SKILL.md`

1. Read source: `~/.claude/plugins/cache/claude-plugins-official/superpowers/4.3.0/skills/systematic-debugging/SKILL.md`.
2. Create `agents/skills/systematic-debugging/SKILL.md` with:
   - Frontmatter: `name: systematic-debugging`, `description: 4-phase root cause debugging methodology. Use when encountering bugs, test failures, or unexpected behavior before proposing fixes.`
   - Sections: Purpose, Scope, Inputs, Outputs, Procedure.
   - Preserve the 4-phase structure (reproduce, bisect, isolate, fix), the anti-patterns table, and the "never guess" discipline.
   - Remove any Claude-specific tool references. Keep methodology agent-agnostic.
3. Commit: `feat(skills): add systematic-debugging methodology skill`

---

### Task 2: test-driven-development

**File(s):** `agents/skills/test-driven-development/SKILL.md`

1. Read source: `~/.claude/plugins/cache/claude-plugins-official/superpowers/4.3.0/skills/test-driven-development/SKILL.md`.
2. Create `agents/skills/test-driven-development/SKILL.md` with:
   - Frontmatter: `name: test-driven-development`, `description: RED-GREEN-REFACTOR discipline with iron laws. Use when implementing features or bugfixes, before writing implementation code.`
   - Preserve the iron laws, the RED-GREEN-REFACTOR cycle, the rationalizations table ("I'll write tests after" etc.), and the checkpoint discipline.
   - Remove any plugin-specific references.
3. Commit: `feat(skills): add test-driven-development methodology skill`

---

### Task 3: verification-before-completion

**File(s):** `agents/skills/verification-before-completion/SKILL.md`

1. Read source: `~/.claude/plugins/cache/claude-plugins-official/superpowers/4.3.0/skills/verification-before-completion/SKILL.md`.
2. Create `agents/skills/verification-before-completion/SKILL.md` with:
   - Frontmatter: `name: verification-before-completion`, `description: Evidence-before-claims gate. Use when about to claim work is complete, before committing or reporting done.`
   - Preserve the gate function concept, the common failures table, and the "run it, read it, confirm it" discipline.
   - Remove any plugin-specific references.
3. Commit: `feat(skills): add verification-before-completion methodology skill`

---

### Task 4: brainstorming

**File(s):** `agents/skills/brainstorming/SKILL.md`

1. Read source: `~/.claude/plugins/cache/claude-plugins-official/superpowers/4.3.0/skills/brainstorming/SKILL.md`.
2. Create `agents/skills/brainstorming/SKILL.md` with:
   - Frontmatter: `name: brainstorming`, `description: Socratic design refinement before implementation. Use before any creative work — features, components, or behavior changes.`
   - Preserve the hard gate (must explore before implementing), the Socratic question process, and the checklist.
   - Remove any plugin-specific references.
3. Commit: `feat(skills): add brainstorming methodology skill`

---

### Task 5: receiving-code-review

**File(s):** `agents/skills/receiving-code-review/SKILL.md`

1. Read source: `~/.claude/plugins/cache/claude-plugins-official/superpowers/4.3.0/skills/receiving-code-review/SKILL.md`.
2. Create `agents/skills/receiving-code-review/SKILL.md` with:
   - Frontmatter: `name: receiving-code-review`, `description: Technical rigor when handling review feedback. Use when receiving code review findings, before implementing suggestions.`
   - Preserve the "verify before accepting" discipline, the pushback protocol for incorrect feedback, and the anti-pattern of performative agreement.
   - Remove any plugin-specific references.
3. Commit: `feat(skills): add receiving-code-review methodology skill`

---

### Task 6: frontend-design

**File(s):** `agents/skills/frontend-design/SKILL.md`

1. Read source: `~/.claude/plugins/cache/claude-plugins-official/frontend-design/236752ad9ab3/skills/frontend-design/SKILL.md`.
2. Create `agents/skills/frontend-design/SKILL.md` with:
   - Frontmatter: `name: frontend-design`, `description: Distinctive, production-grade frontend interfaces. Use when building web components, pages, or applications to avoid generic AI aesthetics.`
   - Preserve the design thinking process, typography/color/motion/spatial composition guidelines, and the anti-generic-AI-slop principles.
   - Remove any plugin-specific references.
3. Commit: `feat(skills): add frontend-design creative methodology skill`

---

### Task 7: Validate and Distribute

**File(s):** All 6 skills

1. Run `telec sync` to validate all artifacts and distribute to runtimes.
2. Verify no validation errors.
3. Spot-check that skills appear in `~/.claude/skills/`, `~/.codex/skills/`, `~/.gemini/skills/`.
4. Fix any validation issues found.
5. Commit any fixes: `fix(skills): address validation issues from telec sync`

---

### Task 8: Branch Alignment Verification

**File(s):** `teleclaude/cli/telec.py`, `teleclaude/cli/config_cli.py`, `teleclaude/config/runtime_settings.py`, `teleclaude/install/install_hooks.py`, `teleclaude/invite.py`, `tools/test.sh`, `docs/project/spec/telec-cli-surface.md`, `todos/roadmap.yaml`, targeted `tests/*`

1. Confirm the todo requirements explicitly include these non-skill surfaces.
2. Run targeted regression tests covering invite fallback output, install/runtime path handling, and run-agent/demo workflows exercised by this branch.
3. Run `make lint` and ensure no new lint/type violations.
4. If failures occur, apply minimal corrective changes in-scope and re-run checks.
5. Keep any non-skill edits limited to contract-alignment; defer unrelated work.

---

## Phase 2: Validation

### Task 2.1: Quality Checks

- [ ] `telec sync --validate-only` passes with no errors
- [ ] All 6 skills distributed to all 3 runtime directories
- [ ] No Claude-specific tool references in any skill content
- [ ] Each skill follows the artifact schema (frontmatter + required sections)
- [ ] Branch alignment surfaces are explicitly represented in requirements and this plan
- [ ] Targeted regression tests for branch alignment surfaces pass
- [ ] `make lint` passes with no new errors

### Task 2.2: Content Verification

- [ ] Each skill preserves the core methodology discipline from its source
- [ ] No verbatim copy — content is adapted to our schema

---

## Phase 3: Review Readiness

- [ ] Requirements reflected in created files
- [ ] Implementation tasks all marked `[x]`
- [ ] Deferrals documented if applicable
