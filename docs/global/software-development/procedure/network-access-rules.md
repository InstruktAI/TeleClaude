---
activation_trigger: 'Use when writing or delivering code that opens outbound connections, or when a per-connection firewall prompts for a binary this repository ships'
description: "Grant a project's own binaries outbound network access through rules committed in the repository that ships them — Little Snitch on macOS, OpenSnitch on Linux. Optional and host-dependent; a no-op where no such filter runs."
visibility: 'public'
---

# Network Access Rules — Procedure

## Goal

An application's binaries reach the network without a per-connection outbound
firewall prompting a human on every connection and every rebuild. The rules that
grant them live in the repository that ships those binaries, committed alongside
the code that opens the connections.

This is the network half of operating a locally built application autonomously;
the identity half is `software-development/procedure/macos-stable-code-signing`.

The procedure is **optional and host-dependent**. It applies only where a
per-connection outbound filter is installed and prompting:

- **macOS** — Little Snitch.
- **Linux** — OpenSnitch.
- **Neither present** — nothing to declare and nothing to apply. That is a no-op,
  not a skipped step.

## Preconditions

- The repository ships binaries that open outbound connections.
- The host has been checked for a per-connection outbound filter. Detection
  precedes authoring; absent a filter, the procedure ends here.

## Steps

### 1. Author the rules at the convention path

Every project carries its own rules at the same location, so an agent in any
repository knows where to read and where to write:

```
docs/specs/rules/networking/little-snitch/
docs/specs/rules/networking/open-snitch/
```

The rules are **committed, never ephemeral**. An agent reads the committed rules
and extends them; it does not re-derive them per run.

### 2. Declare this repository's own binaries

Rules name the binaries this repository ships. A rule matching any process is not
a declaration of what an application needs — it is the removal of the filter.

For rule syntax, read the vendors' own format documentation (linked under
See Also) rather than a copy of it.

### 3. Honor the addressing constraint

Both filters match a binary by absolute path, and neither expands anything:

- **Little Snitch** matches a full executable path — no tilde, no environment
  variable, no relative path — or a code identity of the form
  `identifier.DEV_TEAM_ID/IDENTIFIER`. A self-signed machine-local authority
  carries no team ID, so the code-identity form is unavailable to locally built
  artifacts and the path form is the only one left.
- **OpenSnitch** matches `process.path` through an operator whose type may be
  `simple` or `regexp`, so one committed rule covers a path that varies by
  account.

The asymmetry decides portability. An OpenSnitch rule spans accounts through a
pattern. A Little Snitch rule cannot: it carries no pattern form, so a binary
installed under a user's home directory yields a rule correct on exactly one
account — a machine-local artifact rather than a committed one. Install binaries
at an account-neutral path where a committed macOS rule has to cover a fleet.

### 4. Accept the rules on the host

Acceptance is not symmetric, and the difference decides what can be automated:

- **Little Snitch has no additive command-line verb.** `rulegroup` only enables or
  disables groups that already exist, and `restore-model` replaces the whole
  model. A rule file is handed to the application — see step 5.
- **OpenSnitch applies by file drop** into the daemon's rules directory. On Linux
  hosts this is owned by the project's install flow.

### 5. Apply the committed file on the host

Little Snitch registers the `.lsrules` document type, so the committed file is
applied by opening it from the checkout:

```
open docs/specs/rules/networking/little-snitch/<name>.lsrules
```

Launch Services hands the file to Little Snitch, which presents its own import
confirmation. The confirmation is per machine and happens once; the file being
opened is the reviewed, committed one, so no copy of it is transcribed by hand.

`open` addresses the GUI login session. It works over SSH while that session is
active, and fails where the machine has no logged-in session — that is a host
state, not a defect in the rules.

The rules travel with the repository checkout the host already has, so the
reviewed source and the applied bytes are the same file. The repository is the
trust boundary.

### 6. Reflect a new binary or destination as part of delivery

Work that ships a new binary opening outbound connections, or opens a new
destination for an existing one, updates the committed rules in the same
delivery. A connection the code makes and no rule declares is a prompt waiting to
fire on the next host or the next rebuild.

## Outputs

- Committed rule files at the convention path in the repository that ships the
  binaries.
- On macOS, a machine that has imported the committed `.lsrules` file once.
- On Linux, rules applied to the daemon's rules directory by the install flow.

## Recovery

- **A prompt returns after a rebuild.** The rule is bound to something the rebuild
  changed. Confirm the binary's path is unchanged and its signed identity is stable
  per `macos-stable-code-signing`; an ad-hoc or unsigned artifact presents a new
  identity on every build.
- **A newly declared rule is not honored.** The filter has not reloaded. Restart its
  daemon, then retry.
- **`open` reports no application, or nothing happens.** Little Snitch is not
  installed on that host, or no GUI login session is active. Neither is a reason
  to hand-enter rules on the host instead.

## Discipline

The committed rules are the source of truth and the filter is downstream of them.
An agent that meets a prompt reaches for the committed file, not for the filter's
own interface, because a rule entered by hand lives on one machine and is lost to
every other. A rule names the binaries this repository ships; reaching for a
match-any-process rule ends the prompting by removing the filter, which is the
failure this procedure exists to prevent. The formats are stable, so rules are
extended rather than re-derived per run. Where no such filter runs the procedure
is inert — that is a no-op, never a step to work around.

## See Also

- ~/.teleclaude/docs/software-development/procedure/macos-stable-code-signing.md — the identity half: a rule survives a rebuild only when the binary's identity does.
- https://help.obdev.at/littlesnitch6/adv-lsrules-file-format — Little Snitch `.lsrules` format reference.
- https://github.com/evilsocket/opensnitch/wiki/Rules — OpenSnitch rule format reference.
