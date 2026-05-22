## Slug resolution

`$ARGUMENTS` is optional.

- Explicit normal slug: call the lifecycle state machine for that slug.
- Explicit holder slug: let the state machine resolve direct children. Do not read or execute holder artifacts as prepare/work input.
- No slug for work: let `telec todo work` scan the roadmap for runnable work. A holder with no work-runnable direct child is skipped so it cannot starve later ready work.
- Holder children come from roadmap `group_slug`, never from slug prefixes, holder state, or `after` dependencies.
