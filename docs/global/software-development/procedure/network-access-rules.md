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
- **OpenSnitch** matches `process.path` through a `simple` operator; a regular
  expression is not a documented operand type there.

A committed rule file is therefore portable only where the binaries it names live
at a user-independent path. Binaries installed under a user's home directory
produce a rule that is correct on exactly one account — a machine-local artifact
rather than a committed one, and a reason to install them somewhere account-neutral.

### 4. Accept the rules on the host

Acceptance is not symmetric, and the difference decides what can be automated:

- **Little Snitch has no additive command-line verb.** `rulegroup` only enables or
  disables groups that already exist, and `restore-model` replaces the whole
  model. Accepting a new rule group is therefore a **one-time subscribe per
  machine, through the GUI**.
- **OpenSnitch applies by file drop** into the daemon's rules directory. On Linux
  hosts this is owned by the project's install flow.

### 5. Reach the rules over the transport

A host-level `RULES_BASE_URL` environment variable points at the HTTPS
byte-serving endpoint that publishes repository files. Subscription paths are
addressed relative to the repository root.

When the variable is unset the transport is **absent — a defined state, not a
failure**: the rules stay committed and inert, and a host adopts them once the
transport is configured.

The endpoint is a **trust boundary**: a subscribing host applies the rules it
serves, and the subscription authenticates the endpoint rather than the rule
content. Point `RULES_BASE_URL` only at an access-gated endpoint that publishes
the committed rules, and treat the repository history over those rules as the
record of what it may serve.

### 6. Reflect a new binary or destination as part of delivery

Work that ships a new binary opening outbound connections, or opens a new
destination for an existing one, updates the committed rules in the same
delivery. A connection the code makes and no rule declares is a prompt waiting to
fire on the next host or the next rebuild.

## Outputs

- Committed rule files at the convention path in the repository that ships the
  binaries.
- On macOS, a machine subscribed once to the published rule group.
- On Linux, rules applied to the daemon's rules directory by the install flow.

## Recovery

- **A prompt returns after a rebuild.** The rule is bound to something the rebuild
  changed. Confirm the binary's path is unchanged and its signed identity is stable
  per `macos-stable-code-signing`; an ad-hoc or unsigned artifact presents a new
  identity on every build.
- **A newly declared rule is not honored.** The filter has not reloaded. Restart its
  daemon, then retry.
- **The transport is unreachable or unset.** The rules remain committed and inert.
  Configure `RULES_BASE_URL`; do not hand-enter rules on the host instead.

## See Also

- ~/.teleclaude/docs/software-development/procedure/macos-stable-code-signing.md — the identity half: a rule survives a rebuild only when the binary's identity does.
- https://help.obdev.at/littlesnitch6/adv-lsrules-file-format — Little Snitch `.lsrules` format reference.
- https://github.com/evilsocket/opensnitch/wiki/Rules — OpenSnitch rule format reference.
