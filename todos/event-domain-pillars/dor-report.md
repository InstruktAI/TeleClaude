# DOR Report: event-domain-pillars

## Draft Assessment

### Actions Taken

1. **Requirements rewritten** — aligned with actual codebase patterns:
   - Replaced `DomainEvent` Pydantic subclass approach with `EventSchema` + catalog
     registration pattern (matching `teleclaude_events/schemas/software_development.py`)
   - Replaced `guardian.yaml` per-domain files with `DomainGuardianConfig` within
     `DomainConfig` (matching `event-domain-infrastructure` design)
   - Replaced `init.yaml` manifests with config seeding via `telec init` / `telec config`
   - Acknowledged existing 9 software-development events as extend-only
   - Corrected cartridge directory convention to `~/.teleclaude/company/domains/{name}/cartridges/`
     with `manifest.yaml` + module pattern

2. **Implementation plan rewritten** — restructured to match codebase:
   - Phase 1 now verifies upstream dependencies and establishes naming conventions
   - All pillar phases use catalog registration, cartridge manifest + module pattern,
     and config entry YAML blocks
   - Software development phase extends existing schemas instead of replacing
   - Removed phantom `DomainEvent` base, `GuardianConfig.from_yaml()`, `DomainInitEntry`
   - Added codebase patterns table with concrete file references

3. **Demo.md populated** — real validation blocks with Python assertions against the
   catalog, plus a guided presentation walkthrough

### Assumptions

- `event-domain-infrastructure` will ship `CartridgeManifest`, `DomainConfig`,
  `DomainGuardianConfig`, and `discover_cartridges()` as specified in its implementation
  plan. If these are not available at build time, cartridge manifests and config entries
  are authored as YAML data files validated manually.
- `event-signal-pipeline` will ship `signal-ingest`, `signal-cluster`, `signal-synthesize`
  utility cartridges. If not available, marketing's `feed-monitor` cartridge ships as a
  documented stub.
- The `trust_threshold` field on `DomainGuardianConfig` is supported by the upstream
  infrastructure. If not, it is documented as a config value with no runtime enforcement
  until infrastructure ships.

### Open Questions

1. **Cartridge `event_types` field**: The `CartridgeManifest` schema from infrastructure
   includes an `event_types` subscription list — is this in the manifest spec or is
   subscription declared differently? Need to verify once infrastructure ships.
2. **Config seeding mechanism**: How does `telec init` seed domain config blocks? Is there
   an existing hook or does this todo need to add one? The infrastructure plan mentions
   `telec config patch` but `telec init` may need a domain-discovery step.
3. **Naming convention for non-domain events**: Signal pipeline events use `signal.*`
   prefix, system events use `system.*`. The marketing feed-monitor bridges between
   `signal.synthesis.ready` and `domain.marketing.feed.synthesis_ready`. Is this the
   intended cross-domain pattern?

### Gate Readiness (Draft)

- **Intent & success**: Clear. Four pillars, each with schemas + cartridges + config.
- **Scope & size**: Moderate. Four pillars are broad but each is a pattern repetition.
  Could be parallelized across builders. Fits a single session if done sequentially.
- **Verification**: Good. Demo has concrete assertions. Tests defined.
- **Approach known**: Yes — catalog registration pattern is well-established. Cartridge
  convention depends on upstream but is well-documented.
- **Dependencies**: Two upstream todos (`event-domain-infrastructure`, `event-signal-pipeline`)
  are not yet built. This is the primary risk. Plan accounts for stubs.
- **Integration safety**: Pure content addition — no runtime changes, no breaking changes
  to existing schemas.
