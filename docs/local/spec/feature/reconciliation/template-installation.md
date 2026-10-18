---
description: Every repository-owned template TeleClaude installs onto a machine or
  into a project is rendered and named by one contract — double-brace placeholders
  resolved from supplied values then the environment, unresolved placeholders failing
  the installation, and dot_-marked path segments installed as dot-prefixed names.
---

# Template Installation — Spec

## What it is

TeleClaude installs repository-owned templates in several places: service
definitions during machine installation; the TeleClaude home's repository layer
and every declared person and company home's documentation baselines, before
home activation; every home master and help desk that is absent, whenever
convergence seeds it
(`local/projects/teleclaude/spec/feature/reconciliation/home-template-materialization`);
TeleClaude-owned git hooks into project and home repositories; and project
skeleton files and a project's local documentation baselines during project
initialization. Each installation renders the template's placeholders and places
the result under a name derived from the template's path. One rendering contract
and one naming contract govern all of them, so a template behaves the same
wherever it is installed.

What an installation does with the rendered result — refreshing a differing
target, prompting before replacing a project-owned file, preserving a hook it
does not own, or reloading a service — remains the installing surface's own
contract, except for a template whose name marks it create-once: every surface
writes that template's target only while the target is absent.
The shared rule is that the rendered content, never the raw template, is what
the surface compares against its target, so an unchanged rendered result leaves
the target untouched.

## Canonical fields

- **Placeholder.** `{{NAME}}`: two opening braces, an identifier of letters,
  digits, and underscores that does not start with a digit, and two closing
  braces, with no whitespace inside. Text of any other shape is not a
  placeholder and is copied unchanged — including runtime references such as
  `${HOME}` or `$HOME` that the installed file resolves for itself.
- **Value resolution.** A placeholder takes the value the installing surface
  supplies for that name. A name the surface does not supply takes the value of
  the environment variable of the same name. A supplied value wins over the
  environment for the same name. A value is inserted as given; text it carries
  is never itself rendered.
- **Unresolved placeholder.** A placeholder with neither a supplied value nor an
  environment variable fails the installation. The failure names the template
  and every unresolved placeholder in it, and the target is neither written nor
  replaced.
- **Dot marker.** Within a template tree installed as files, every path segment
  authored as `dot_<name>` — file or directory — is installed as `.<name>`.
  Segments carrying neither the `dot_` nor the `create_` marker keep their
  names, including names that begin with an underscore or hold a dot after
  their first character. A template tree carries no literal dot-prefixed
  segment. Templates installed from an explicit source-to-target file list are
  named by that list, and line fragments merged into another file are never
  installed as files.
- **Create-once marker.** Within a template tree installed as files, a file
  segment authored as `create_<name>` is installed as `<name>`, and its target
  is written only while it is absent: an existing target is kept as it is,
  whatever its content. The marker comes first on a segment that also carries
  the dot marker, so `create_dot_<name>` installs as `.<name>`. A directory
  segment carrying it fails the installation before any target is written. The
  template is still rendered, so an unresolved placeholder in it fails the
  installation even when its target already exists.
- **Tracked sources.** A template tree installed as files consists of the files
  the canonical checkout tracks under it. A file lying in the tree that the
  checkout does not track — ignored or untracked, such as a file manager's
  residue or a generated entrypoint — is never installed and never fails the
  installation.
- **Content comparison.** An installing surface compares the rendered content
  with its target. A target already equal to the rendered content is left
  untouched, and the surface runs no action reserved for a changed target.

### Use cases

#### UC-TIN1: A supplied value takes precedence over the environment

#### UC-TIN2: An unresolved placeholder fails the installation

#### UC-TIN3: Runtime references are installed verbatim

#### UC-TIN4: dot_-marked segments install as dot-prefixed names

#### UC-TIN5: An unchanged rendered result leaves its target untouched

#### UC-TIN6: A create-once template never replaces its target

#### UC-TIN7: Only tracked template files are installed

## Known caveats

- A value rendered into a template installed at a location a repository
  retains enters that repository's history. A template carrying a
  machine-specific placeholder belongs at a location the receiving repository
  does not retain.
- Removing a template does not remove what an earlier installation placed.
