---
description: Bring a person's assistant into existence or bring it up to date — workspace, mail authorization, and the first knowledge mined from their own correspondence and confirmed by them.
activation_trigger: Use when someone asks to set up, start, or connect their assistant, when they ask for help getting their email or calendar working, when a person has no workspace or no authorized mail account yet, or when onboarding is re-run to pick up steps published since they last ran it.
---

# Personal Assistant Onboarding — Procedure

## Required reads

@~/.teleclaude/docs/personal/policy/assistant-conduct.md
@~/.teleclaude/docs/personal/spec/person-knowledge.md

## Goal

Leave the person with an assistant that can read their mail and calendar, write
in their voice, and act under a mandate they granted knowingly — and leave a
record of what was completed so a later run continues rather than restarts.

## Preconditions

- The person exists in configuration and their slug is known.
- The tool spec for their mail provider has been read. Which provider they use
  is theirs to state, not something to infer from their address.

## Steps

1. **Read the current state before changing any of it.** Onboarding is a
   reconciliation, not a script: it runs against a workspace that may be empty,
   partly built, or complete. Establish what exists — the workspace, the
   `knowledge/` directory and its documents, whether an account is already
   authorized — and compute what is missing. Nothing already correct is redone,
   and nothing is asked about that the workspace already answers.

2. **Materialize what is absent.** Create the workspace root and its
   `knowledge/` directory if they are not there. Silent creation is correct here:
   it is structure, not content, and nothing about it is the person's to decide.

3. **Establish the mandate before asking for any credential.** Tell them plainly
   what the assistant will be able to do once authorized, and what it will never
   do: settings are never touched on any path, and nothing is sent that they did
   not ask for. Their answer sets the width of the mandate. Do not proceed to
   authorization while they are still deciding.

4. **Walk them through authorization.** The ceremony belongs to the provider's
   tooling and is documented with that tool, not restated here. The agent's part
   is to run the commands, name each thing the person must do in their browser
   one at a time, and wait. Never paste a credential into a message, a log, or a
   commit; the tool ingests it from a path.

5. **Confirm the grant is what was agreed, and read the evidence carefully.**
   Exercise it: one permitted read, and one operation the mandate excludes. The
   read succeeding shows the grant works. The excluded operation establishes the
   absence of a permission in exactly one case: the provider answered with an
   identified insufficient-scope denial. Every other failure is inconclusive and
   leaves the grant unknown — a tool that blocked the command locally has proven
   only its own configuration, and a provider can equally refuse for a disabled
   API, an account restriction, or an endpoint policy, none of which say
   anything about what was granted. What counts as identified is not a
   judgement call: the provider's own documented insufficient-scope error
   identifier is present in the response, as recorded in that tool's spec.
   Where the tool's documentation names no such identifier, there is nothing to
   match against and the result is inconclusive by default. Where the provider
   offers a way to read the granted scopes back directly, prefer that over
   inferring them from any failure at all. Report what each result does and does
   not establish.

6. **Mine their own correspondence for a first draft of who they are.** From
   their sent mail: the addresses they send from and what each is for, the
   correspondents that recur, and a handful of messages per identity that read
   as characteristically them. This is reading, and it happens once. Nothing is
   written to the workspace from it yet.

7. **Propose, and let them correct.** Show the identity registry and the
   candidate examples as a proposal in one pass, not a document at a time. They
   confirm, cut, and correct. What survives is written to `knowledge/`, one
   document per subject, in their words rather than a summary of them.

8. **Record what this run completed** in the person's own data, so a later run
   can offer the difference rather than the whole. When a run finds steps
   completed under an older routine, it offers only what is new.

9. **Finish with one real piece of work**, supervised — a briefing of what is in
   their inbox and one draft in the right voice from the right identity. This is
   the first exercise of the mandate, and it is reported afterwards, not asked
   about first.

## Outputs

- A workspace with a `knowledge/` directory holding the confirmed identity
  registry, priorities, and voice examples.
- An authorized mail account whose grant has been demonstrated to match what the
  person agreed to.
- A record of the steps this run completed.
- One briefing and one draft the person has seen.

## Recovery

- **Authorization fails or the person abandons the ceremony.** Leave the
  workspace as it stands and say exactly which step remains. A partly onboarded
  person is a normal state, not a broken one; the next run resumes there.
- **The excluded operation in step 5 succeeds.** The grant is wider than agreed.
  Say so plainly, do not proceed to mining, and re-authorize narrowly.
- **The excluded operation fails as anything other than an insufficient-scope
  denial.** The grant is unverified, not confirmed — whether the block was
  local, an API that is switched off, or an account restriction. Say so, and
  either establish the scopes another way or record the width of the grant as
  unknown. A failure whose cause is unidentified is never evidence about what
  was granted.
- **Mining finds too little to propose** — a thin sent folder, or one identity
  used for everything. Propose what there is and say what is missing. An
  assistant with one confirmed example is better than one with five invented.
- **The person contradicts something already recorded.** The new instruction is
  checked against what is in force before it is stored, and a contradiction is
  surfaced rather than stacked beside its opposite.
