---
id: 'project/spec/feature/context/hooks-frontmatter-per-agent-transform'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Artifact "hooks" frontmatter is preserved for Claude output and stripped for Codex/Gemini output during transpilation. Distinct from live agent CLI hook installation.'
---

# Hooks Frontmatter Per-Agent Transform — Spec

## Required reads

- @docs/project/spec/domain/context.md

## What it is

The hooks-frontmatter transform is a per-agent artifact transpilation rule
that conditionally preserves or removes the `hooks` key from emitted artifact
frontmatter based on the target agent. For Claude targets, `hooks` is left
intact; for Codex and Gemini targets, the key is stripped before frontmatter
is dumped. This is a STATIC artifact transform owned by the context bounded
context — it is distinct from the live agent CLI hook installation that
plumbs runtime hooks into each agent's settings file at project init/setup
time (owned by `teleclaude/install/configure_agent_cli.py`).

The two concepts share the word "hooks" but live in different parts of the
system. Confusing them mixes a documentation/frontmatter concern with a
runtime plumbing concern.

## Canonical fields

### Use cases

```
Scenario: Claude target preserves hooks in artifact frontmatter
  Given a source artifact whose frontmatter contains a "hooks" field
  When the transpiler runs _filter_frontmatter for the Claude target
  Then the "hooks" key is left intact in the metadata
  And dump_frontmatter emits the "hooks" field in the Claude artifact's YAML frontmatter
```

```
Scenario: Codex target strips hooks from artifact frontmatter
  Given a source artifact whose frontmatter contains a "hooks" field
  When the transpiler runs _filter_frontmatter for the Codex target
  Then the "hooks" key is removed from the metadata
  And dump_frontmatter emits the Codex frontmatter without a "hooks" field
  And the Codex CLI does not see an unsupported field at parse time
```

```
Scenario: Gemini skill receives a belt-and-braces hooks strip
  Given a source skill whose frontmatter contains a "hooks" field
  When transform_skill_to_gemini processes the skill
  Then transform_skill_to_gemini explicitly pops "hooks" from the skill frontmatter
  And _filter_frontmatter also removes "hooks" earlier in the pipeline
  And the emitted Gemini TOML contains no "hooks" entry
```

```
Scenario: Parameters are always stripped regardless of agent
  Given a source artifact with both "hooks" and "parameters" fields
  When the transpiler processes the artifact for any target agent
  Then "parameters" is removed from the emitted frontmatter for every target
  And "parameters" is rendered as an HTML-comment preamble in the body
  And "hooks" follows the per-agent strip-or-preserve rule defined above
```

```
Scenario: Runtime hook installation is independent of the artifact transform
  Given a project is being initialized via configure_agent_cli.py
  When merge_hooks runs to install runtime hooks into Claude settings.json, Gemini hook config, and Codex hooks.json
  Then the runtime hook installation operates on agent CLI configuration files
  And it does NOT inspect artifact frontmatter "hooks" fields
  And the artifact-level transform and the runtime-level installation never share state
```

### Implementation pointers (v1)

- `scripts/distribute.py:175-180` — `ArtifactFrontmatter` TypedDict with the `hooks` field
- `scripts/distribute.py:263-274` — `transform_skill_to_gemini()` explicit `hooks` pop (defense in depth)
- `scripts/distribute.py:313-318` — `_filter_frontmatter()` conditional `hooks` strip per agent
- `scripts/distribute.py:321-339` — `_prepare_post()` pipeline that applies the filter
- `teleclaude/install/configure_agent_cli.py:183-239` — `merge_hooks()` runtime hook installation (different concept; cross-referenced for contrast)
- `teleclaude/install/configure_agent_cli.py:302-324` — Claude and Gemini runtime hook map builders (NOT context-owned)

### Cross-context references

- **agent_runtime** — Owns the runtime hook plumbing for live agent CLIs. The
  context bounded context only owns the per-agent artifact frontmatter
  transform; the actual installation of runtime hooks into Claude's
  `settings.json`, Gemini's hook config, and Codex's `hooks.json` happens in
  `teleclaude/install/configure_agent_cli.py` at project init/setup time.

## Known caveats

- The `hooks` field in artifact frontmatter and the runtime hook installation
  are TWO different concepts that happen to share a name. The context
  bounded context owns the artifact transform; agent_runtime / install owns
  runtime installation. Documentation and reviewers must keep the two
  separated.
- Whether the artifact-frontmatter `hooks` field is consumed by any Claude
  runtime path or whether it is documentary-only is unresolved in the v1
  source. The strip-for-non-Claude policy is the conservative default
  (avoid emitting a field that the parser might reject); a future migration
  may either formalize or remove the field.
- Skills get a belt-and-braces strip for Gemini: both `_filter_frontmatter()`
  in the shared pipeline AND `transform_skill_to_gemini()` explicitly pop
  `hooks`. Either alone would suffice today, but both are wired in so that a
  pipeline refactor cannot accidentally leak `hooks` into Gemini output.
- No equivalent conditional transform exists for the `parameters` field — it
  is stripped universally because the preamble-injection step
  (`_inject_parameter_preamble`) takes ownership of it for every target
  agent. Per-agent variation applies only to `hooks`.
- Renaming or aliasing `hooks` in artifact frontmatter would silently bypass
  the per-agent filter. The strip rule keys off the literal `"hooks"` field
  name in metadata.
