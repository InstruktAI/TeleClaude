---
visibility: public
number: 0103
date: 2026-09-25
description: A process with no session identity document names its agent session by the session id its own agent harness carries in the environment, and the client resolves that session from the record the platform keeps for it.
---

# Foreign Sessions Are Named by Their Harness Session Id — ADR

## Context

An agent session TeleClaude did not start — an agent CLI started by hand from a
terminal, an agent hosted by another tool, a subagent of either, a scheduled run
outside the daemon's runtime — has no session identity document. Its hooks
already reach the platform: an unknown session start creates a session record,
and that record takes its person from the login of the terminal the agent was
started from. What such an agent's own processes lack is a way to name that
record. They resolve as the person at the terminal, or as no one, so
session-scoped acts fail for work that belongs to a verified person: arming the
session's own reminders, dispatching a commit review keyed to the session, and
git operations the wrapper gates on a role it reads from the document.

ADR-0079 answered this by enrolling the session's root process through a
kernel-attested connection to the daemon, because every harness-supplied
identifier travels in a payload the caller controls and an identifier that could
not be forged would have been a credential. ADR-0101 then moved authorization
into the client and made the daemon trust the identity a request carries: every
agent runs as the same operating-system user, the platform's checks guard
against mistakes rather than adversaries, and identity is verified once where it
enters the platform and carried inside from there. Under that model the
objection to a caller-supplied identifier no longer holds: a process can already
name any session by writing a session identity document, and the daemon accepts
whatever identity a request carries.

Claude Code and Codex give each process they start the session id they report in
their hook payloads, through an environment variable they set, and DeepSeek's
harness documents the same for every shell call; no such equality is established
for Gemini's harness. That id is minted when the harness starts its session and
is inherited by everything the session starts, which is the carriage the
in-process identity model asks for.

## Decision

A process with no session identity document names its session by the session id
its own agent harness carries in its environment. The client resolves that id to
the open session record whose native session id it is, and from then on the
process acts as that session exactly as a process inside a session TeleClaude
started acts as its own. The environment variable each harness uses is declared
once, per agent, in the agent registry. A session identity document, when
present, is the only session reference consulted; a harness id that names no
open session, or ids naming more than one, leave the process resolved at the
edge from its terminal login.

## Consequences

- The three observed failures resolve without a new launch path, a daemon
  round trip, or per-invocation enrollment: the record the hooks already create
  is the session, and its person was resolved at the edge when it was recorded.
- Coverage follows the harness, not the launch path. A harness that carries no
  session id in its environment, or one whose carried id is not the id its hooks
  report, keeps today's edge behavior. Adding one is a registry declaration once
  the equality is established.
- The first commands an agent runs before its session-start hook has been
  recorded resolve at the edge. Nothing is widened meanwhile.
- A process that sets a harness variable to another session's id acts as that
  session. This is the exposure ADR-0101 accepted for the session identity
  document and for carried request identity, not a new one: the identifier is a
  reference, not a credential.
- Nested harnesses of different vendors leave several harness ids in one
  environment. The platform does not guess which is innermost: several ids
  naming distinct open sessions resolve at the edge.
- A session reached this way is a headless record. Input delivered to it, a
  fired reminder included, revives the session under the platform's existing
  delivery rules for headless sessions; this decision changes nothing there.

## Alternatives Considered

**Enrol the session root through an attested connection (ADR-0079).** Rejected:
it exists to authenticate callers at the daemon, which ADR-0101 removed, and it
added an integration point per launch path for a check the platform no longer
performs.

**Mint a session identity document in a launcher shim.** A wrapper placed ahead
of each agent binary would allocate a session directory and document before the
agent starts. Rejected: it duplicates the hook path's session creation, covers
only launches that pass through the shim — not an agent host that calls a binary
by absolute path — and changes the temporary directory of every agent a person
starts by hand.

**Export the session id from a session-start hook.** One harness lets a hook
publish environment for later tool calls. Rejected as the mechanism: it covers
one harness, and the id the same harness already exports makes it unnecessary.

**Derive the session from process ancestry.** Rejected for the reasons ADR-0079
records: the ancestor that hosts a session is undetermined from process evidence
alone.

## See Also

- docs/project/adr/0079-external-session-roots-are-enrolled-not-derived.md
- docs/project/adr/0101-clients-authorize-and-the-daemon-trusts-carried-identity.md
