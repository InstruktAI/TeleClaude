---
description: 'The "what do you want me to build?" game for new projects: harvest, classify the workload, run the branching checklist, present the brief as the contract, then scaffold via the flavor''s own generator.'
activation_trigger: 'A new project/repository is about to be created — a design handoff arrived, a reference repo was named, or the human asks to build a new site, app, service, or tool from scratch.'
---

# Greenfield Intake — Procedure

## Goal

Turn "build me X" into a filled **brief** — workload class, flavor, answered
questions, activated baseline branches — that becomes the definition of done.
The human answers only what is genuinely theirs (taste, business, brand);
every production default ships silently from the applicable baseline.

## Preconditions

- The delivery portfolio and the applicable baseline policies are loaded.
- Any design handoff (design-spec, art, HTML prototypes) and any named
  reference repo are available for harvesting.

## Steps

1. **Harvest before asking.** Read the design handoff, reference repo, and any
   provided content. Everything derivable from those is pre-answered and
   presented as an assumption to veto — never asked as an open question.

2. **Reference-parity audit** (when a reference repo is named). Enumerate
   _every_ capability of the reference — routes, i18n, SEO plumbing, forms,
   integrations, tests, CI — into an adopt/adapt/drop matrix. "Rebuild X like
   Y" means parity by default; every _drop_ requires explicit human sign-off.
   The matrix joins the brief and is verified line-by-line before "done".

3. **Classify the workload** against the delivery portfolio table; state the
   resulting flavor and delivery target as a proposal with one line of
   reasoning.

4. **Run the question rounds** — closed questions with proposed defaults; each
   answer unlocks or kills a branch. Ask only what the checklist marks as the
   human's; execute every unlocked branch at full depth without further
   questions.

   **Identity & content**
   - ☐ Product: what it is, for whom, emotional register _(harvest from design spec)_
   - ☐ Voice law: who speaks first person on which surfaces; system voice elsewhere
   - ☐ Copy vetoes and tone rules (client-specific)
   - ☐ Content sourcing: who supplies copy, translations, photography
   - ☐ Legal pages needed? → localized slugs, formal-instrument voice, footer links

   **Languages** — multi-language? ☐ no / ☐ yes → which, which default, untranslatable brand terms → _unlocks the full i18n baseline branch_

   **Reach**
   - ☐ Canonical host: bare or www (other 301s)
   - ☐ Meta description copy (propose drafts; brand voice is the human's)
   - ☐ Social image material: photo available or generated brand card
   - ☐ Analytics? (and consent implications)
   - ☐ Theme support: light only or light+dark

   **Interaction**
   - ☐ Forms: which, delivery destination (service/email/API), post-send experience
   - ☐ Contact strategy: form vs direct channels (WhatsApp/mail/social)
   - ☐ Scheduling/booking? ☐ no / ☐ yes → availability source, request-vs-instant
     model, durations (fixed/variable), prices shown or not → _unlocks the
     scheduling baseline branch_
   - ☐ Auth, payments, dashboards? → _app-class signal: revisit classification_

   **Delivery & operations**
   - ☐ Hosting per portfolio (confirm blessed target)
   - ☐ Domain: registrar, DNS plan — **inventory existing DNS records before
     any nameserver change**; mail routing + SPF/DMARC when the domain does email
   - ☐ Third-party keys: enumerate every allowed origin (bare, www, previews, localhost)
   - ☐ Owner handover: README the owner can read, config table for operational knobs

5. **Present the brief** — classification, matrix, answers, activated
   branches — as the contract. Baseline items appear as delivered scope, not
   questions. On approval, the brief feeds the normal prepare/PRD machinery.

6. **Scaffold via the flavor's own generator** (see the flavor's scaffolding
   snippet), wire the quality gates and CI _before_ feature work — for sites,
   follow `software-development/procedure/setup-visual-regression` — and end
   by running `telec projects init` for the TeleClaude plumbing.

## Outputs

- The approved brief (with parity matrix when applicable) — the definition of
  done for the build.
- A scaffolded repo with gates, buttons, and CI wired, ready for the prepare
  lifecycle.

## Recovery

- Answers that invalidate the classification (e.g. auth appears mid-intake)
  re-run step 3; the brief is re-presented.
- If the human cannot answer a question, record the assumption taken and
  proceed — assumptions are listed in the brief.

## Discipline

The failure mode this procedure kills: building the visible fraction of the
request and making the human drive every invisible default, one correction at
a time. A named reference repo is a contract, not inspiration — audit it
before building. Ask closed questions once, up front; after the brief is
approved, deliver the baselines in silence. An open question that the design
handoff, the reference repo, or a baseline already answers is a violation.

## See Also

- ~/.teleclaude/docs/software-development/concept/delivery-portfolio.md
- ~/.teleclaude/docs/software-development/policy/frontend-production-baseline.md
- ~/.teleclaude/docs/software-development/policy/ci-pipeline-conventions.md
- ~/.teleclaude/docs/creative/procedure/lifecycle/overview.md — the design handoff this intake consumes.
