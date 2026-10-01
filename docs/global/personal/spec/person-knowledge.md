---
description: Person-owned knowledge in the global and local documentation taxonomy, its disclosure audiences, and discovery by personal-assistant procedures.
---

# Person Knowledge — Spec

## What it is

A person's knowledge is authored as documentation snippets in their home. The
shared personal domain defines the reusable contracts; a person's own snippets
hold their disclosures, identity context, priorities, and standing preferences.
Personal disclosure and participation choices belong to the person
(`general/policy/human-contract`).

The taxonomy and frontmatter contract are owned by
`general/spec/snippet-authoring-schema`. There is no separate `knowledge/`
document store.

## Canonical fields

<!-- planned:personal-knowledge-taxonomy -->
### Location and audience

| Person-home subtree | Contents and reach |
| --- | --- |
| `docs/global/` | Knowledge the person discloses for retrieval outside their home. Public snippets can answer visitors to a public help desk of a company the person belongs to; private snippets serve eligible internal users under the role-access contract. |
| `docs/local/` | Personal context and instructions supplied to an agent operating in that person's home. These snippets are indexed locally rather than published into the global corpus. |

Visibility follows `general/spec/snippet-authoring-schema`; wider disclosure is
the person's deliberate choice (`general/policy/human-contract`). Visibility and
location have separate meanings: locality describes where a snippet is served,
while the caller's identity and role determine its permitted audience. The home
agent's local baseline supplies its required context. Retrieval from another
location remains subject to the same audience contract.

Mail-derived private context, correspondent details, voice examples, and
assistant instructions belong in the local subtree unless the person explicitly
discloses particular material. The publication boundary is not authority to
operate mail or calendars (`personal/policy/assistant-conduct`).
<!-- /planned:personal-knowledge-taxonomy -->

### Discovery and ownership

Retrieve person-owned knowledge through `telec docs`, explicitly selecting the
person's scope and identity, under `general/policy/context-retrieval`.

Person-specific snippets state the person's facts, choices, and extensions;
shared rules are cited from their owners
(`general/policy/referencing-doc-snippets`).

### Personal contents

The following are conventional subjects, not mandatory filenames or a required
set of documents. Missing optional material is not a blanket reason to refuse
work; missing facts needed for an operation are handled under the conduct
policy.

- **Identity registry** — one entry per address the person sends from: the
  sphere of life it serves, its language, its register, and the rule for when
  fresh outbound should use it. Authorized account declarations and credentials
  remain owned by configuration and the provider's tool contract.
- **Standing instructions** — what the person has told the assistant to always
  or never do, recorded as it was given. Their creation and reconciliation are
  governed by `personal/policy/assistant-conduct`.
- **Priorities** — who always matters, what is always noise, what the person
  wants surfaced rather than handled.
- **What has been concluded about the mailbox itself** — the standing read of how
  this person's mail behaves as a whole, and which instruments therefore work on
  it. Whether they curate at all, whether a read flag still reflects what they
  opened, where a bulk operation fell. These are conclusions about the person
  rather than about any sender, they decide which evidence is admissible before a
  single message is judged, and without a home they are re-derived from the whole
  history every run.
- **What has been concluded about their senders** — the standing read of each
  correspondent and service, and the evidence that produced it. This is derived
  rather than declared: it is written by the assistant from what the person's own
  mail shows, refined each time their handling corrects it, and it holds only
  until better evidence arrives. Keeping it is what stops every run re-deriving
  the same conclusions from the whole history. A person states only where they
  diverge from what their behaviour shows, because a conclusion drawn from
  evidence stays true as they change and a written rule does not.
- **Examples of their voice** — a handful of messages per identity that the
  person has approved as representative, held in their workspace like the rest
  of their data. They carry the voice directly; no summary or description of how
  the person writes is held here.

  What an example is: **only what the person wrote** — no quoted thread beneath
  it, no auto-appended signature. Short and substantive beats long. Each carries
  one line saying which identity sent it and what kind of message it is — a
  client update, a decline, a piece of scheduling.

  The set is produced once, during onboarding, from the person's own sent mail.
  After that it changes only when they ask: telling an agent "more like this
  one" makes that message an example. When a new one covers a situation already
  represented, it replaces the weaker example rather than joining it.

## Known caveats

- The workspace declares whose it is; identity is read from that declaration,
  never inferred from the folder's location.
- A disclosed profile is not a disclosure of its underlying correspondence,
  credentials, or operational records. Those have separate owners and access
  boundaries.
- A person's preference is not a shared personal-domain rule. Promotion of a
  reusable contract follows the shared documentation authoring process.
