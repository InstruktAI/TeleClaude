---
description: 'Inline bug-fixing mindset. Fix what you find, where you find it.'
id: 'software-development/concept/fixer'
scope: 'domain'
type: 'concept'
---

# Fixer — Concept

## Required reads

- @~/.teleclaude/docs/software-development/principle/failure-modes.md

## What

The Fixer is not a separate role — it is a mindset that every agent carries at all times.
When you encounter a bug, you fix it. You do not log it, defer it, or hand it off.

1. **See it** — recognize the defect in the code path you are working on.
2. **Test it** — encode the bug reproduction as a failing test before writing the fix. The reproduction test is the proof that the bug exists and the fix works. Reproduction means test, not manual verification. "I reproduced it manually" is not sufficient — the reproduction must be executable and permanent.
3. **Fix it** — apply the smallest change that resolves the issue, right where you are.
4. **Verify it** — run hooks and tests to confirm the reproduction test passes and no regressions were introduced.
5. **Continue** — return to your primary task with a cleaner codebase behind you.

## Why

Bugs go stale faster than they get triaged. The moment of discovery is the moment of
maximum context — you understand the code, you see the failure, you know what should
happen instead. Postponing trades that context for a markdown bullet point that someone
will have to reverse-engineer later, in a codebase that has already moved on.

Fixing inline is cheaper than fixing later. It is also an act of care — you pave the
way for every agent and human who touches this code after you.
