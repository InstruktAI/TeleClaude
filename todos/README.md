# TeleClaude TODOs

**Last Updated:** 2025-11-08

---

## Current Status

✅ **Architecture refactoring COMPLETE** (2025-11-08)

All architectural violations have been resolved. The codebase now implements:

- **Observer Pattern**: AdapterClient has NO daemon reference, daemon subscribes to events
- **Module-Level Singleton**: session_manager accessed via import
- **Origin/Observer Broadcasting**: One interactive adapter, observers with `has_ui` flag
- **Event-Driven Architecture**: All communication via events
- **AdapterClient as Central Hub**: ALL adapter operations flow through AdapterClient
- **No Direct Coupling**: Removed all direct adapter references outside AdapterClient

See `docs/architecture.md` for comprehensive documentation with mermaid diagrams.

---

## Archive

The `archive/` folder contains completed specs and historical planning documents:

- `redis_adapter.md` - Original Redis adapter specification (✅ implemented)
- `mcp_server.md` - MCP server design (⚠️ Telegram bot restriction analysis)
- `refactoring.md` - Functional programming refactoring (✅ completed)
- `testing_refactor.md` - Testing improvements (✅ completed)
- `tests_investigation.md` - Test suite analysis (historical)
- `hardening_action_plan.md` - Production hardening (historical)

**Completed and removed:**

- `ARCHITECTURAL_VIOLATIONS.md` - ✅ All violations resolved (2025-11-08)
- `CURRENT_WORK.md` - ✅ Phases 1-3 completed (2025-11-08)
- `ARCHITECTURE_SEQUENCE_DIAGRAMS.md` - ✅ Integrated into `docs/architecture.md`

---

## Future Work

### High Priority

- REST API ingress configuration for public HTTPS links
- AI-generated session titles using Claude API
- Live config reload (watch `config.yml`)

### Medium Priority

- Terminal recording (text + video with rolling window)
- Multi-device terminal sizing (detect client type)
- WhatsApp adapter implementation
- Slack adapter implementation

### Nice to Have

- Session templates (predefined setups)
- Command aliases (user-configurable)
- Multi-hop AI communication (Comp1 → Comp2 → Comp3)

---

## Development Workflow

1. **Check archive/** for reference specs
2. **Read docs/architecture.md** for current architecture patterns
3. **Create new todo file** when starting major work
4. **Keep only ONE active work file** at a time
5. **Archive completed work** and update this README

---

**End of TODO Index**
