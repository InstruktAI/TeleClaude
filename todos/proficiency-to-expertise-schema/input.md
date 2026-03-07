# proficiency-to-expertise-schema — Input

## Summary

Replace the flat `proficiency` field on PersonEntry with a structured `expertise` Pydantic model. This is the foundation that all other expertise work depends on.

## Schema Change

Current:
```yaml
proficiency: expert  # single flat level
```

New:
```yaml
expertise:
  teleclaude: novice                  # flat level — platform fluency, no sub-areas
  software-development:
    default: advanced
    backend: expert
    frontend: intermediate
    devops: advanced
    data: intermediate
    security: intermediate
  marketing:
    default: novice
  publishing:
    default: intermediate
    articles: intermediate
  creative:
    default: novice
    copywriting: intermediate
```

### Domain pillars

| Domain | What it is |
|--------|-----------|
| **teleclaude** | Platform fluency — flat level, no sub-areas |
| **software-development** | Technical domain knowledge |
| **marketing** | Promotion & strategy |
| **publishing** | Content production & distribution |
| **creative** | Craft & design |

### Design decisions

- No global default level. Unlisted domains = AI assumes intermediate or asks.
- teleclaude is a flat level (no sub-areas). All other domains have named sub-areas + a domain default.
- Levels: novice, intermediate, advanced, expert (same four as today).
- Freeform sub-area keys allowed — schema validates levels, not key names.

## Touchpoints

| Component | File | Lines | Change needed |
|-----------|------|-------|--------------|
| Schema | `config/schema.py` | 127-133 | Replace proficiency with expertise model |
| API DTO | `api_models.py` | 155-163 | Mirror new structure |
| Config save | `config_handlers.py` | 269 | Serialize nested model |
| Schema tests | `test_config_schema.py` | 405-421 | New validation tests |

## Migration

- `proficiency` field stays supported during transition — if present, maps to a single-domain expertise entry (software-development.default = proficiency value).
- Existing person configs without expertise: fall back to intermediate (same as today's default).
- `extra="allow"` on PersonEntry already permits forward-compatible fields.

## Validation rules

- All level values must be one of: novice, intermediate, advanced, expert.
- Domain keys should include the known pillars but allow freeform.
- Sub-area keys within domains are freeform — schema validates level values only.
- Flat domain (string value) and structured domain (dict with default + sub-areas) are both valid.
