---
id: 'general/spec/expertise-taxonomy'
type: 'spec'
domain: 'general'
scope: 'global'
description: 'Fixed domain taxonomy for PersonEntry.expertise — domains, subdivisions, proficiency levels, and extension policy.'
---

# Expertise Taxonomy — Spec

## What it is

The canonical taxonomy for the `PersonEntry.expertise` field. Agents use this to know which domains and subdivisions exist, what proficiency levels mean, and how to set or interpret expertise values. Without this spec, agents guess domain keys — producing inconsistent, unvalidated data.

The taxonomy feeds the Calibration principle: per-domain proficiency signals tell agents how to communicate about specific topics, not just at a general level.

## Canonical fields

### Proficiency levels

Defined in `teleclaude/config/schema.py` as `ProficiencyLevel`:

| Level          | Meaning                                                                  |
| -------------- | ------------------------------------------------------------------------ |
| `novice`       | No meaningful experience. Needs full guidance.                           |
| `intermediate` | Working knowledge. Can follow guidance with context.                     |
| `advanced`     | Deep experience. Collaborates as a peer. Needs only architectural input. |
| `expert`       | Authoritative. Leads decisions. Needs only blockers surfaced.            |

### Domains

Four fixed domains. Adding a new domain requires a schema update and a change to this spec.

| Domain                 | Description                                    |
| ---------------------- | ---------------------------------------------- |
| `software-development` | Code, infrastructure, architecture, tooling.   |
| `creative`             | Visual design, writing, UX, branding, media.   |
| `marketing`            | Growth, content, analytics, campaigns, SEO.    |
| `customer-relations`   | Support, sales, account management, community. |

### Starter subdivisions

Subdivisions within each domain. New subdivisions can be added without a schema change — they are starter recommendations, not an exhaustive enumeration.

**software-development**

`python`, `typescript`, `go`, `rust`, `devops`, `databases`, `api-design`, `frontend`, `backend`, `testing`, `security`, `architecture`

**creative**

`visual-design`, `copywriting`, `ux`, `branding`, `video`, `audio`

**marketing**

`content-marketing`, `seo`, `social-media`, `analytics`, `email-campaigns`, `paid-ads`, `growth`

**customer-relations**

`support`, `sales`, `account-management`, `community`, `success`

### JSON shape

The `PersonEntry.expertise` field type is `dict[str, ProficiencyLevel | dict[str, ProficiencyLevel]]`.

Domain-level proficiency (flat):

```json
{
  "software-development": "expert",
  "creative": "intermediate",
  "marketing": "novice",
  "customer-relations": "advanced"
}
```

Subdivision-level proficiency (nested):

```json
{
  "software-development": {
    "python": "expert",
    "typescript": "advanced",
    "frontend": "intermediate",
    "architecture": "expert"
  },
  "creative": "novice",
  "marketing": "novice",
  "customer-relations": {
    "support": "advanced",
    "sales": "intermediate"
  }
}
```

Mixed (domain-level for some, subdivision-level for others):

```json
{
  "software-development": {
    "python": "expert",
    "typescript": "advanced",
    "devops": "advanced",
    "databases": "advanced",
    "architecture": "expert"
  },
  "creative": "intermediate",
  "marketing": "novice",
  "customer-relations": "advanced"
}
```

When a domain has a single `ProficiencyLevel` string, it applies uniformly to all subdivisions. When a domain has a dict, only listed subdivisions carry a signal — unlisted subdivisions are unknown (not novice).

### Extension policy

- **New subdivision:** Add to the relevant domain list in this spec. No code change required — the schema accepts arbitrary string keys within the dict.
- **New domain:** Requires updating this spec, adding the domain key to validation logic in `teleclaude/config/schema.py`, and updating any downstream consumers.

## Known caveats

- The Pydantic schema validates structure (dict of strings or nested dicts) but does not yet validate domain or subdivision keys against this taxonomy. Validation against the taxonomy is future work.
- Unlisted subdivisions in a nested dict mean "unknown proficiency," not "novice." Agents should not infer a level for subdivisions that are absent.
- The `proficiency` field on `PersonEntry` is deprecated in favor of `expertise`. It provided a single global level; `expertise` provides per-domain granularity.
