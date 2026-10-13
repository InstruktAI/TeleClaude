---
description: Every reference to a company, person, project, or documentation domain resolves against what this computer has registered, and an unresolved reference is refused once, the same way everywhere — naming what is missing, on which computer, and the existing registration surface that supplies it.
visibility: internal
delivered_by: [missing-publisher-owner-surfacing]
---

# Referent Resolution — Spec

## Required reads

- @docs/local/spec/domain/config.md
- @docs/local/spec/feature/config/project-registry.md

## What it is

Declarations and requests name registered things by slug: a project's owner
company or person, a roster's company and projects, a session's selected
company, a procedure activation's home, a request addressed to a project on
another computer, and a documentation identity whose first segment is a domain.
Each such name is a referent, and whether it resolves is a fact about one
computer: what that computer has registered — its registry entries, the person
and company declarations under its platform home, and the domains its registered
projects declare they publish.

Resolution is one published answer. A referent that is registered on the
computer answering resolves to its record. A referent that is not is refused,
and the refusal is the same wherever the reference was met and whichever
computer it was made from: it names the referent's kind and slug, the computer
that answered, and the registration surface for that kind on that computer.
The registration surfaces are the existing ones — the company and person
initialization commands and project adoption (`general/spec/tools/telec-cli`);
a documentation domain is registered by adopting the project that publishes it
and publishing that project
(`local/projects/teleclaude/spec/feature/context/sync-pipeline-orchestration`).
Nothing is provisioned on the referrer's behalf: no checkout is cloned, no
company or person is created, and no replacement for the missing thing is
inferred from the referrer's surroundings.

A well-formed reference to an unregistered referent is not malformed. The
refusal is the whole answer: a consumer that meets it neither invents a
substitute, continues with a partial record, nor restates the condition in its
own words. Once the named surface has registered the referent, the same
reference resolves unchanged.

## Canonical fields

- **Referent kinds.** Company, person, project, and documentation domain. A
  domain's record is the registered project whose publishing declaration names
  it.
- **Answer.** The referent's record on the answering computer, or the refusal.
- **Refusal.** Kind, slug, the answering computer, and that kind's registration
  surface there. A request addressed to another computer receives that
  computer's refusal as that computer produced it
  (`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).

### Use cases

#### UC-CFG-REF1: A registered referent resolves to its record

```gherkin
Scenario Outline: A reference to something registered here resolves
  Given a <referent> registered on this computer
  When a declaration or request names it by slug
  Then it resolves to that referent's record on this computer
  And no other computer is consulted

  Examples:
    | referent                        |
    | company                         |
    | person                          |
    | project                         |
    | domain a registered project publishes |
```

#### UC-CFG-REF2: An unregistered referent is refused with its registration surface

```gherkin
Scenario Outline: A reference to something not registered here is refused
  Given a well-formed slug that names no <referent> registered on this computer
  When a declaration or request names it
  Then the referrer is refused rather than given a partial or substituted record
  And the refusal names the kind and slug, the computer that answered, and how to register that kind there
  And the refusal does not present the reference as malformed

  Examples:
    | referent                        |
    | company                         |
    | person                          |
    | project                         |
    | domain a registered project publishes |
```

#### UC-CFG-REF3: Registering the referent makes the same reference resolve

```gherkin
Given a reference that was refused because its referent was not registered on this computer
And the referent has since been registered here through the surface the refusal named
When the same reference, unchanged, is resolved again
Then it resolves to the referent's record
```

### Cross-context references

- **config** itself consumes this answer for a project's declared owner
  (`local/projects/teleclaude/spec/feature/config/project-ownership`) and for a
  company roster's members and assignments
  (`local/projects/teleclaude/spec/feature/config/organizational-membership`).
- **agent_runtime** consumes it for a session's selected company
  (`local/projects/teleclaude/spec/feature/agent_runtime/company-scoped-session-context`)
  and for the home a procedure activation names
  (`local/projects/teleclaude/spec/feature/agent_runtime/procedure-standing-agent`).
- **context** consumes it for the domain a snippet reference or requested
  identity names
  (`local/projects/teleclaude/spec/feature/context/snippet-frontmatter-validation`,
  `local/projects/teleclaude/spec/feature/context/doc-snippet-three-phase-retrieval`).
- **integration** consumes it for the project a request addressed to another
  computer names
  (`local/projects/teleclaude/spec/feature/integration/computer-addressed-execution`).
- **identity** owns what a resolved person or company means — membership,
  binding, visibility — and grants nothing from resolution alone
  (`local/projects/teleclaude/spec/feature/identity/person-context-binding`).

## Known caveats

- A domain resolves only through a registered project's publishing declaration.
  A publisher's checkout that is present on the computer but never adopted
  there registers nothing, so references into its domains are refused until it
  is adopted (`local/projects/teleclaude/spec/feature/config/project-registry`).
- Resolution is per computer. A referent registered on one computer in the
  fleet is unregistered on another until it is registered there; nothing
  propagates registrations.
