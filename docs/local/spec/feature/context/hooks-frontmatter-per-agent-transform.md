---
description: 'Artifact "hooks" frontmatter is preserved for Claude output and stripped for Codex/Gemini output during transpilation. Distinct from live agent CLI hook installation.'
visibility: 'public'
---

# Hooks Frontmatter Per-Agent Transform — Spec

## Required reads

- @docs/local/spec/domain/context.md

## What it is

The hooks-frontmatter transform is a per-agent artifact transpilation rule
that conditionally preserves or removes the `hooks` key from emitted artifact
frontmatter based on the target agent. For Claude targets, `hooks` is left
intact; for Codex and Gemini targets, the key is stripped before frontmatter
is emitted. This is a STATIC artifact transform owned by the context bounded
context — it is distinct from the live agent CLI hook installation that
plumbs runtime hooks into each agent's settings file at project setup
time (owned by agent_runtime).

The two concepts share the word "hooks" but live in different parts of the
system. Confusing them mixes a documentation/frontmatter concern with a
runtime plumbing concern.

## Canonical fields

### Use cases

### Cross-context references

- **agent_runtime** — Owns the runtime hook plumbing for live agent CLIs. The
  context bounded context only owns the per-agent artifact frontmatter
  transform; the actual installation of runtime hooks into each agent CLI's
  configuration files happens at project setup time under the
  agent_runtime context.

## Known caveats

- The `hooks` field in artifact frontmatter and the runtime hook installation
  are TWO different concepts that happen to share a name. The context
  bounded context owns the artifact transform; agent_runtime owns runtime
  installation. Documentation and reviewers must keep the two separated.
- Whether the artifact-frontmatter `hooks` field is consumed by any Claude
  runtime path or whether it is documentary-only is unresolved. The
  strip-for-non-Claude policy is the conservative default (avoid emitting a
  field that the parser might reject); a future migration may either
  formalize or remove the field.
- Skills get a belt-and-braces strip for Gemini: both the shared per-agent
  frontmatter filter AND the Gemini skill transform explicitly remove
  `hooks`. Either alone would suffice today, but both are wired in so that a
  pipeline refactor cannot accidentally leak `hooks` into Gemini output.
- No equivalent conditional transform exists for the `parameters` field — it
  is stripped universally because the preamble-injection step takes
  ownership of it for every target agent. Per-agent variation applies only
  to `hooks`.
- Renaming or aliasing `hooks` in artifact frontmatter would silently bypass
  the per-agent filter. The strip rule keys off the literal `"hooks"` field
  name in metadata.
