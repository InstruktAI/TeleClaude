---
description: Claude Code instruction-file loading — when AGENTS.md is read instead of or beside CLAUDE.md, the Project instructions setting and where it is honoured, user-scope CLAUDE.md, imports, and exclusions.
---

# Claude Code — Instruction Files (CLAUDE.md and AGENTS.md)

## Default: CLAUDE.md or AGENTS.md

- Claude Code reads `AGENTS.md` directly from v2.1.277. Before that, and in
  sessions where the built-in `agents-md` plugin is disabled, only `CLAUDE.md`
  files load.
- By default (`claude-md-or-agents-md`) it reads `AGENTS.md` only when no
  `CLAUDE.md`, `.claude/CLAUDE.md`, or `CLAUDE.local.md` exists in the working
  directory **or any directory above it**. One such file anywhere on the path
  makes Claude read the `CLAUDE.md` files only.
- Files that do not count for that check, and keep loading alongside
  `AGENTS.md`: `~/.claude/CLAUDE.md`, the managed-policy `CLAUDE.md`, and
  `.claude/rules/` files.
- At session start every `AGENTS.md` and `.claude/AGENTS.md` in the working
  directory and above loads. A subdirectory's `AGENTS.md` loads when Claude
  reads a file there and that subdirectory has none of the three `CLAUDE.md`
  files.
- Never read: `AGENTS.local.md`, `AGENTS.override.md`, anything under
  `.agents/`.

## The Project instructions setting

- Values: `claude-md-or-agents-md` (default), `claude-md-and-agents-md`,
  `claude-md`, `managed-only`.
- `claude-md-and-agents-md` loads each directory's `CLAUDE.md` files first and
  its `AGENTS.md` after them. An `AGENTS.md` already loaded through a
  `CLAUDE.md` import or symlink is not read twice.
- Set through `/config` (**Project instructions**) or in settings under
  `pluginConfigs["agents-md@builtin"].options.instructionFiles`.
- Honoured in `~/.claude/settings.json`, a `--settings` file, and managed
  settings. **Ignored in project and local settings files.**

## User scope

- User-scope instructions load only from `~/.claude/CLAUDE.md` (plus
  `~/.claude/rules/`). No user-scope `AGENTS.md` is documented.

## Imports and exclusions

- `@path` imports are expanded inside `AGENTS.md` as in `CLAUDE.md`; relative
  paths resolve from the importing file; recursion is capped at four hops.
- Import grammar: an `@path` may appear anywhere in the file; relative and
  absolute paths are allowed, and the path may be extensionless or any file
  type (`@README`, `@package.json`). The path ends at the first unescaped
  space; a backslash before a space escapes it. A path wrapped in quotes is
  not imported, with or without backslashes. Parsing skips Markdown code spans
  and fenced code blocks, so `` `@README` `` stays literal.
- An import resolving outside the working directory is external. For an
  `AGENTS.md` read through the setting it loads only if external imports were
  already approved for that project, with no prompt; a `CLAUDE.md` shows the
  approval dialog instead. User-scope files load their imports without the
  dialog (except in Cowork desktop sessions).
- `claudeMdExcludes` patterns match absolute file paths, apply at every
  settings layer (arrays merge across layers), and apply to `AGENTS.md` files
  too — a broad pattern such as `*/**/AGENTS.md` suppresses every `AGENTS.md`.

## Differences for AGENTS.md read through the setting

- `InstructionsLoaded` hooks do not fire for it (they do for an `AGENTS.md`
  imported or symlinked from a `CLAUDE.md`).
- With `CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD` set, an `--add-dir`
  directory's `AGENTS.md` does not load.

## Gaps/Unknowns

- Whether a first session after upgrading from v2.1.276 or earlier reads
  `AGENTS.md` is documented as "in some cases" not; the next session does.

## Sources

- https://code.claude.com/docs/en/memory — "AGENTS.md", "Choose which instruction files load", "Import additional files", "Exclude specific CLAUDE.md files" (fetched 2026-09-30; import grammar re-checked 2026-10-01).
