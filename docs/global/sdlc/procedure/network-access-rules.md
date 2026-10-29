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
the identity half is `sdlc/procedure/macos-stable-code-signing`.

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

### 2. Declare the binaries this repository's code runs

Rules name the binaries this repository ships and the tools its install flow
installs for its code to run, each with the destinations it needs. A rule
matching any process is not a declaration of what an application needs — it is
the removal of the filter.

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
  model. Accepting a new rule group is therefore a **one-time subscribe per
  machine, through the GUI**.
- **OpenSnitch applies by file drop** into the daemon's rules directory. On Linux
  hosts this is owned by the project's install flow.

### 5. Publish the rules where hosts subscribe

A subscribing filter fetches its rules over HTTPS from a host with a publicly
trusted certificate. The repository's own GitHub Pages site is that host: a
scheduled job in the repository builds the served rule file from the committed
source and deploys it to Pages, and commits nothing. A host subscribes to
`https://<owner>.github.io/<repository>/<file>`. Until the job has published,
the committed rules are inert — a defined state, not a failure.

A package manager that installs each version at its own path gives every
upgrade a new path, and macOS reports a running binary by its resolved path,
never by a symlink to it. Homebrew installs a formula under
`<prefix>/Cellar/<formula>/<version>[_<revision>]/`, with `/opt/homebrew` and
`/usr/local` as its prefixes. The committed source therefore names the formula
and the binary's path inside the formula's folder, never a version. The job
expands each entry into one rule per version and prefix: it reads the current
version from the package manager's API and keeps every version the published
file already carries, so a host still running an older version keeps its rule.

A binary signed with a Developer ID carries a team ID, so its rule names its code
identity (`identifier.TEAM_ID/IDENTIFIER`) instead of a path and survives every
upgrade unchanged.

Little Snitch subscribes once per machine to the published file as a remote rule
group. "Disable new allow rules" is turned off for that group; otherwise every
version the job adds arrives disabled.

The published file is a **trust boundary**: a subscribing host applies the rules
it serves, and a subscribing filter offers no hook to verify a signature over the
content it fetches. Integrity rests on TLS for channel integrity and server
authentication, on the repository's own Pages site as the only origin, and on a
source that is reviewed and committed before the job publishes it.

### 6. Reflect a new binary or destination as part of delivery

Work that ships a new binary opening outbound connections, or opens a new
destination for an existing one, updates the committed rules in the same
delivery. A connection the code makes and no rule declares is a prompt waiting to
fire on the next host or the next rebuild.

## Outputs

- Committed rule files at the convention path in the repository that ships the
  binaries.
- The rule file the repository's job publishes on its Pages site.
- On macOS, a machine subscribed once to the published rule group.
- On Linux, rules applied to the daemon's rules directory by the install flow.

## Recovery

- **A prompt returns after a rebuild.** The rule is bound to something the rebuild
  changed. Confirm the binary's path is unchanged and its signed identity is stable
  per `macos-stable-code-signing`; an ad-hoc or unsigned artifact presents a new
  identity on every build.
- **A newly declared rule is not honored.** The filter has not reloaded. Restart its
  daemon, then retry.
- **A prompt names a version the published file lacks.** The publishing job has not
  run since that upgrade. Run it; do not hand-enter rules on the host instead.

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

- ~/.teleclaude/docs/sdlc/procedure/macos-stable-code-signing.md — the identity half: a rule survives a rebuild only when the binary's identity does.
- https://help.obdev.at/littlesnitch6/adv-lsrules-file-format — Little Snitch `.lsrules` format reference.
- https://github.com/evilsocket/opensnitch/wiki/Rules — OpenSnitch rule format reference.
