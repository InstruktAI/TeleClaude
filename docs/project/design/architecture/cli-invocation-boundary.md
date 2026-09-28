---
description: The path from a shell to a telec command handler — which checkout's code
  runs, the one auth gate that alone precedes dispatch, and how a worktree exercises
  its own change without reaching live state.
visibility: internal
---

# CLI Invocation Boundary — Design

## Purpose

Give every change that touches the `telec` entry path one account of what happens
between a shell and a command's handler: which checkout's code runs, what may run
before dispatch, and where the caller is authorized. Per-command access lives in
`project/design/cli-authorization-matrix`; caller identity and its carriage live in
`project/spec/identity-and-auth`; the command catalog lives in `CLI_SURFACE`. This
design owns only the path that connects them.

## Inputs/Outputs

**Inputs**

- The wrapper that was invoked: the global `telec`, or a checkout's own `bin/telec`.
<!-- planned-change:worktree-code-uses-its-home -->
- The home the process runs against (`TELECLAUDE_HOME`, fixed before the interpreter
  starts; the default is the live home).
<!-- change:worktree-code-uses-its-home -->
- The home the process runs against: for code loaded from a slug worktree,
  that worktree's home; otherwise `TELECLAUDE_HOME`, read once when the
  process starts, defaulting to the live home.
<!-- /planned-change:worktree-code-uses-its-home -->
- The command line.
- The caller's identity evidence: the session identity marker and the session row it
  names, or the terminal login outside a session; and the people roster that maps a
  person to a role.

**Outputs**

<!-- planned-change:authorize-person-roles-at-scope -->
- The command's handler runs with a resolved, authorized caller, or
- a refusal before the handler runs: an unidentified caller, or a role the command
  does not admit.
<!-- change:authorize-person-roles-at-scope -->
- The pre-dispatch gate refuses an unidentified caller or a role outside a band
  it can decide before dispatch.
- A handler whose target is already known runs with full command clearance.
- A handler that resolves a trusted-directory name runs with caller and agent
  admission, then either completes person-band clearance on the selected
  directory or refuses before any project operation or daemon request.
<!-- /planned-change:authorize-person-roles-at-scope -->

## Invariants

1. **The wrapper's location selects the code.** The global `telec` runs the installed
   canonical checkout from any working directory. A checkout's own `bin/telec` runs
   that checkout. The caller's working directory never selects code; handlers still
   receive it as the directory the command acts on.
<!-- planned-change:worktree-code-uses-its-home -->
2. **Worktree code never runs against the live home.** A slug worktree's `bin/telec`
   runs the worktree's code against a home other than the live one. When the caller
   names no home, or names the live home, the wrapper creates a temporary home, runs
   against it, and removes it when the command ends, all within that one process, so a
   caller needs no home of its own for isolation. A caller-named home other than the
   live one is honored; agents never name one (`project/policy/test-moratorium`).
   An unset or empty home is the live home. Any other named home is compared with the
   live home by filesystem identity, so no spelling, symlink, `..` or letter case
   reaches it, and the interpreter receives exactly the location that was checked. A
   home that holds no machine configuration receives a copy of the live one before the
   worktree's code starts; nothing else is copied. The integration worktree is not a
   slug worktree.
<!-- change:worktree-code-uses-its-home -->
2. **Worktree code never runs against the live home.** Code loaded from a
   slug worktree runs against the worktree's home — a clone of the home
   repository the platform provisions with the worktree
   (`project/spec/feature/agent_runtime/isolated-home`) — whatever
   `TELECLAUDE_HOME` says, and refuses at startup, naming that home, when it
   is missing. The worktree's `bin/telec` creates no home. The integration
   worktree is not a slug worktree.
<!-- /planned-change:worktree-code-uses-its-home -->
<!-- planned-change:worktree-code-uses-its-home -->
3. **`telec code` grades a change with the change's own code.** Lint lanes, guardrail
   allowlists, schemas and the rendered command surface that judge a worktree's change
   come from that worktree, while `telec code` itself runs installed code. The
   worktree's grading code runs against a fresh scratch home seeded the same way and
   discarded when grading ends, never against the live home. It runs exactly the checks
   the acting invocation context selects (`project/design/code-commit`), no more and no
   fewer. A worktree that cannot run the selected checks in its own code is refused,
   never graded by installed rules instead. Bookkeeping commands run installed code and
   read and write the live home as usual.
<!-- change:worktree-code-uses-its-home -->
3. **`telec code` grades a change with the change's own code.** Lint lanes, guardrail
   allowlists, schemas and the rendered command surface that judge a worktree's change
   come from that worktree, while `telec code` itself runs installed code. A slug
   worktree's grading code runs against its worktree home and is refused when that
   home is missing; any other checkout's grading code runs against a fresh scratch
   home holding a copy of the machine configuration, discarded when grading ends.
   Neither runs against the live home. Grading runs exactly the checks the acting
   invocation context selects (`project/design/code-commit`), no more and no fewer.
   A worktree that cannot run the selected checks in its own code is refused,
   never graded by installed rules instead. Bookkeeping commands run installed
   code and read and write the live home as usual.
<!-- /planned-change:worktree-code-uses-its-home -->
4. **Only the auth gate precedes dispatch.** Before a handler runs, the CLI reads the
   command surface to identify the command and passes the caller through one gate.
   Nothing else runs, loads, or validates first.
<!-- planned-change:authorize-person-roles-at-scope -->
5. **The gate is cheap and narrow.** It reads the auth the command surface declares for
   the command, and resolves the caller from the session identity marker, one session
   row, and the people roster. A session row is admitted by the marker that names it.
   The gate loads neither the machine configuration nor the ORM, and never validates a
   configuration document beyond the roster it reads, so an invalid document unrelated
   to identity does not lock callers out. Every command the CLI authorizes in process is
   authorized here. A command declared independent of its caller
   (`project/design/cli-authorization-matrix`) passes the gate without any caller
   resolution.
<!-- change:authorize-person-roles-at-scope -->
5. **The gate is cheap and narrow.** It reads the auth the command surface declares for
   the command, and resolves the caller from the session identity marker, one session
   row, the people roster, and the organization facts the command's scope needs — the
   person's company memberships and the ownership declaration of the registered
   project the command acts on, read narrowly as the roster is. A session row is
   admitted by the marker that names it. The gate loads neither the machine
   configuration nor the ORM, and never validates a configuration document beyond
   those identity facts, so an invalid document unrelated to identity does not lock
   callers out. The gate completes person-band clearance when the acted-on object is
   known from the command or an identity record. When a command names a project by
   its machine-configured trusted-directory name, the gate resolves the caller and
   enforces any agent band without loading machine configuration. The handler
   resolves that name through the typed configuration and completes the same
   command's person-band clearance on the exact directory it will use, before
   the command's project operation or any daemon request. An unknown name is
   checked at platform scope before available names are shown. A command declared
   independent of its caller (`project/design/cli-authorization-matrix`) passes
   the gate without any caller resolution.
<!-- /planned-change:authorize-person-roles-at-scope -->
6. **A command pays only for its own dependencies.** Configuration, the ORM, the daemon
   API client, history, mirrors, summarizers and the LLM SDKs load inside the handler
   of a command that needs them. A module shared by several commands imports nothing
   at module scope that one of those commands does not need. The daemon API client is
   loaded only by commands that act through the daemon, and carries no history,
   summarizer or LLM dependency.
7. **The pre-dispatch path is closed.** The set of modules the path before dispatch may
   import is declared, and a guardrail rejects a change that widens it. A command whose
   own work is trivial completes in roughly 200 ms from the shell; the figure is the
   target that shows invariants 4–6 hold, not a limit a change is graded against.

## Primary flows

### Invocation

```mermaid
flowchart TD
    Shell[shell] --> Which{which wrapper?}
    Which -->|global telec| Installed[installed canonical checkout]
    Which -->|checkout bin/telec| Own[that checkout]
    Own --> Slug{slug worktree?}
    Slug -->|no| Interp
<!-- planned-change:worktree-code-uses-its-home -->
    Slug -->|yes| Home{home is the live home?}
    Home -->|yes| Temp[temporary home the wrapper creates and removes]
    Temp --> Interp
    Home -->|no| Interp
<!-- change:worktree-code-uses-its-home -->
    Slug -->|yes| WHome{worktree home exists?}
    WHome -->|yes| Interp
    WHome -->|no| Refuse[refused at startup, naming the missing home]
<!-- /planned-change:worktree-code-uses-its-home -->
    Installed --> Interp[interpreter]
    Interp --> Surface[read command surface]
    Surface --> Gate[auth gate: marker, session row, roster]
<!-- planned-change:authorize-person-roles-at-scope -->
    Gate -->|admitted| Handler[handler loads its own dependencies]
    Gate -->|not admitted| Deny[refused before the handler]
<!-- change:authorize-person-roles-at-scope -->
    Gate -->|target known and cleared| Handler[handler loads its own dependencies]
    Gate -->|trusted-directory name; caller and agent admitted| NamedHandler[handler resolves name through typed config]
    NamedHandler --> TargetCheck[person band at selected directory]
    TargetCheck -->|admitted| Act[project operation or daemon request]
    TargetCheck -->|refused| Deny[refused before action]
    Gate -->|refused| Deny
<!-- /planned-change:authorize-person-roles-at-scope -->
```

### Exercising one's own change from a worktree

An agent in a slug worktree runs its bookkeeping with the global `telec` exactly as
anywhere else. To drive its own change by hand — a help path, a probe of a command it
changed — it calls the worktree's `bin/telec` and nothing more. That process runs the
<!-- planned-change:worktree-code-uses-its-home -->
worktree's code against a temporary home the wrapper creates and removes:
configuration, database and state rooted in the home follow it. The temporary home
starts with a copy of the live machine configuration and nothing else; a probe that
needs more state than that is verified after delivery. State rooted in the project — a checkout's todo store — and the
daemon do not move with the home. A command that writes project state or acts through
the daemon reaches the live one, whose code is delivered code; that behavior is
verified after delivery (`project/policy/test-moratorium`).
<!-- change:worktree-code-uses-its-home -->
worktree's code against the worktree's home, a Git clone of the home repository
the platform provisions with the worktree
(`project/spec/feature/agent_runtime/isolated-home`): configuration, database
and state rooted in the home follow it. The home carries no session record, so
a caller-gated command run this way is refused; a probe that needs more state
than the tracked configuration is verified after delivery. State rooted in the
project — a checkout's todo store — and the daemon do not move with the home.
A command that writes project state or acts through the daemon reaches the live
one, whose code is delivered code; that behavior is verified after delivery
(`project/policy/test-moratorium`).
<!-- /planned-change:worktree-code-uses-its-home -->

## Failure modes

| Condition                                                 | Effect                                                                                                                               |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| Machine configuration is invalid                          | Only commands whose handler needs it fail, each naming the document; caller resolution, validation and repair commands keep working. |
| People roster cannot be read                              | The caller resolves to no identity and receives the unauthorized view; commands needing no caller still run.                         |
| Session marker names no admissible row                    | The caller resolves to no identity inside the session; it is never widened to another identity.                                      |
<!-- planned-change:worktree-code-uses-its-home -->
| Worktree `bin/telec` called with no home or the live home | Runs against a temporary home the wrapper creates and removes in that process; live home untouched.                                  |
| Named home holds no machine configuration                 | A copy of the live one is placed there before worktree code runs; the live home is only read.                                        |
<!-- change:worktree-code-uses-its-home -->
| Worktree code started | Runs against the worktree's provisioned home whatever `TELECLAUDE_HOME` says; live home untouched. |
| The worktree's home is missing | Refused at startup, naming the home; nothing is created. |
<!-- /planned-change:worktree-code-uses-its-home -->
| Daemon unreachable                                        | Only commands that act through the daemon fail; everything else runs.                                                                |
| A change imports a new module on the pre-dispatch path    | The guardrail rejects it before it lands.                                                                                            |

## See Also

- docs/project/adr/0102-a-telec-wrapper-runs-the-checkout-it-belongs-to.md — why the wrapper's location, not the caller's directory, selects the code.
<!-- planned-change:worktree-code-uses-its-home -->
- docs/project/spec/feature/agent_runtime/checkout-code-selection.md — the agent-facing use cases for code selection, the wrapper-owned temporary home, and self-grading.
<!-- change:worktree-code-uses-its-home -->
- docs/project/spec/feature/agent_runtime/checkout-code-selection.md — the agent-facing use cases for code selection, the worktree's home, and self-grading.
<!-- /planned-change:worktree-code-uses-its-home -->
- docs/project/adr/0101-clients-authorize-and-the-daemon-trusts-carried-identity.md — why the caller is authorized in the CLI process.
- ~/.teleclaude/docs/general/principle/trust-and-guardrails.md — why a write to shared state that others have read cannot be repaired by restoring it, and why a refusal names its door.
- docs/project/policy/test-moratorium.md — how changes are verified without tests, and why daemon behavior is verified after delivery.
