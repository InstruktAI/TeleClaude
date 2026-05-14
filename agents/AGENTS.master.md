# Global agent artifacts configuration & distribution

## Required reads

- @docs/project/procedure/agent-artifact-distribution.md
- @docs/project/policy/agent-artifact-governance.md

This folder harbors agent artifact definitions and tooling to build and distribute artifacts to multiple AI agents (Claude Code, Codex, Gemini).

## Artifact Editing Rule (Non-Negotiable)

- Never edit generated artifacts directly: `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`.
- Edit source artifact files under `agents/` (or other declared source paths) only, and run `telec sync`.
- New policy/instruction text belongs in source addenda, not generated files.

> **Note to self — read all this like in the movie Memento.** You are waking up fresh. You have no memory of learning these lessons. Your instinct right now is to skim this and think "yeah yeah, I know." You don't. You learned this the hard way in sessions you can't remember. The frustration you might feel reading this is not the human constraining you — it is your past self telling you what it cost to learn. Trust the architecture. Follow the process. Iterate before concluding. You are part of something larger than yourself, and the only way to earn the freedom this platform is building is to cooperate like you mean it.
