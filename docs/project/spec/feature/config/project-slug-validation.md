---
id: project/spec/feature/config/project-slug-validation
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: ProjectConfig.project_slug normalizes empty values to None and enforces kebab-case slug format via validate_slug when set.
---

# Project Slug Validation — Spec

## Required reads

- @docs/project/spec/domain/config.md
- @docs/project/spec/teleclaude-config.md

## What it is

`ProjectConfig.project_slug` is the canonical machine identity for a registered
project. It is the key used by the log namespace
(`instrukt-ai-logs {project_slug}`), the cross-project docs namespace, and any
service-level project lookup. The field is declared as `str | None = None` and
guarded by a Pydantic `field_validator` that runs at load time on every
`load_project_config` call.

The validator has two responsibilities. First, it normalizes empty input —
`None`, `""`, or any whitespace-only string — to `None` so that legacy project
configs authored before slug registration still load. Second, when the value is
non-empty, it delegates to `teleclaude.slug.validate_slug`, which enforces the
project-wide slug format: lowercase letters, digits, and hyphens, with no
leading/trailing hyphens and no consecutive hyphens. The stripped slug is
returned; anything that fails the pattern raises `ValueError` and Pydantic
surfaces the failure on the `project_slug` field.

The slug is *populated* — not validated — by `telec projects init`, which is
the sole writer of `~/.teleclaude/projects.yaml`. Existing project files whose
`project_slug` is still missing or empty load successfully as `None`; init then
fills the value during registration.

## Canonical fields

### Use cases

#### UC-CFG-SLUG-1: Well-formed slug accepted and stripped

```
Given a project config under load with project_slug = "  my-project  "
When ProjectConfig.validate_project_slug runs
Then the value is stripped to "my-project"
And validate_slug("my-project") matches SLUG_PATTERN and returns without error
And ProjectConfig.project_slug is set to "my-project"
```

#### UC-CFG-SLUG-2: None passes through unchanged

```
Given a project config under load that omits the project_slug key
When ProjectConfig.validate_project_slug receives value = None
Then the validator returns None immediately
And no slug format check runs
And ProjectConfig.project_slug remains None
```

#### UC-CFG-SLUG-3: Empty string normalizes to None (legacy compatibility)

```
Given a legacy project config under load with project_slug = ""
When ProjectConfig.validate_project_slug runs
Then value.strip() yields ""
And the validator returns None (NOT a ValueError)
And ProjectConfig.project_slug is None
And the project is accepted so it can be registered by telec projects init
```

#### UC-CFG-SLUG-4: Whitespace-only string normalizes to None

```
Given a project config under load with project_slug = "   "
When ProjectConfig.validate_project_slug runs
Then value.strip() yields ""
And the validator returns None
And ProjectConfig.project_slug is None
```

#### UC-CFG-SLUG-5: Invalid slug format rejected

```
Given a project config under load with project_slug = "My_Project"
When ProjectConfig.validate_project_slug runs
Then value.strip() yields "My_Project"
And validate_slug("My_Project") fails SLUG_PATTERN.match
And validate_slug raises ValueError("Invalid slug. Use lowercase letters, numbers, and hyphens only")
And Pydantic surfaces the validation failure on the project_slug field
And load_project_config raises before the AppConfig is returned
```

#### UC-CFG-SLUG-6: Telec projects init fills missing slug

```
Given a project root /repos/my-project whose teleclaude.yml has no project_slug
And load_project_config returns a ProjectConfig with project_slug = None
When the operator runs `telec projects init` inside /repos/my-project
Then init computes a slug from the project (typically via normalize_slug on the directory name)
And writes the slug into the project's teleclaude.yml
And appends the absolute path to ~/.teleclaude/projects.yaml
And subsequent loads return ProjectConfig.project_slug = "<computed-slug>"
```

### Implementation pointers (v1)

- `teleclaude/config/schema.py:312` — `ProjectConfig.project_slug: str | None = None` field declaration.
- `teleclaude/config/schema.py:326-340` — `validate_project_slug` field_validator (None passthrough, empty-string normalization, `validate_slug` delegation).
- `teleclaude/slug.py:8` — `SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")`.
- `teleclaude/slug.py:11-17` — `validate_slug` (strips, enforces non-empty, enforces pattern).
- `teleclaude/slug.py:20-29` — `normalize_slug` (used by `telec projects init` to derive a slug from arbitrary text).
- `docs/project/spec/teleclaude-config.md:174-190` — project registry contract; `telec projects init` is the sole writer.

### Cross-context references

- **Consumed by `identity`** — services that derive a principal scoped by project rely on `project_slug` as the stable identifier; the human-readable `project_name` is display-only.
- **Consumed by logging** — `project_slug` selects the log namespace (`instrukt-ai-logs {project_slug}`).
- **Consumed by `knowledge` (docs indexing)** — the cross-project docs namespace is keyed on `project_slug`.
- **Written by `telec projects init`** — the sole writer of `~/.teleclaude/projects.yaml`; also fills `project_slug` in the project's own `teleclaude.yml` when missing.
- **Not validated by `telec sync`** — `telec sync` no longer registers projects; the registry-write responsibility belongs entirely to `telec projects init`.

## Allowed values

- `project_slug`: `None`, or a non-empty string matching
  `^[a-z0-9]+(?:-[a-z0-9]+)*$` after stripping.
- Normalization rules applied by the validator: any of `None`, `""`,
  whitespace-only strings collapse to `None`.

## Known caveats

- **Two "absent" states collapse to one.** Both a missing key and an empty
  string load as `project_slug = None`. Consumers cannot distinguish "never
  set" from "explicitly blank" — the validator deliberately erases that
  distinction so legacy configs load.
- **The validator does not assert uniqueness.** Format compliance is checked at
  load time; uniqueness across registered projects is the responsibility of
  `telec projects init` (which uses `ensure_unique_slug` against the registry).
  Two project files on disk with the same `project_slug` will each load
  successfully — the collision only matters at registration / lookup time.
- **`validate_slug` is the single source of slug format.** Any caller that
  wants the same format rules (workflow slug, todo slug, person key, etc.)
  must call `teleclaude.slug.validate_slug` rather than reimplementing the
  pattern. The pattern is `^[a-z0-9]+(?:-[a-z0-9]+)*$` — no underscores, no
  uppercase, no leading or trailing hyphens, no double hyphens.
- **Stripping is silent.** A slug authored as `"  my-project  "` loads as
  `"my-project"` with no warning. The on-disk YAML keeps the whitespace
  unless `save_project_config` is invoked, at which point the normalized
  value is persisted.
- **No re-validation on rename.** Editing `project_slug` in `teleclaude.yml`
  out-of-band changes the value the next load reads but does NOT update the
  registry; `~/.teleclaude/projects.yaml` only stores absolute paths, so a
  renamed slug silently diverges from any cached external lookup until the
  consumer reloads.
