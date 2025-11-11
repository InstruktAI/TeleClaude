# REST API: Notification Endpoint for Claude Code Hooks - Task Breakdown

> **PRD**: prds/rest-api-notification-endpoint.md
> **Status**: 🚧 In Progress
> **Started**: 2025-01-11

## Implementation Tasks

### Phase 1: SSL Certificate Generation ✅

- [x] **COMPLETED**: Create `scripts/generate-ssl-cert.sh` script
  - Generate self-signed certificate with openssl ✅
  - Create 2048-bit RSA private key ✅
  - Generate certificate valid for 365 days ✅
  - Set Common Name (CN) to localhost ✅
  - Output to `certs/server.crt` and `certs/server.key` ✅
  - Make script executable ✅

- [x] Run certificate generation script
  - Execute `bash scripts/generate-ssl-cert.sh` ✅
  - Verify `certs/server.crt` and `certs/server.key` created ✅
  - Check certificate details with `openssl x509 -in certs/server.crt -text -noout` ✅

- [x] Update `.gitignore`
  - Add `certs/*.key` to ignore private keys ✅
  - Add `certs/*.crt` to ignore certificates (per-machine) ✅

- [x] Add `make certs` command to Makefile
  - Add certs target ✅
  - Update help output ✅
  - Test command works ✅

- [x] Document SSL setup in README.md
  - Add SSL Certificates section ✅
  - Document `make certs` command ✅
  - Note per-machine requirement ✅

### Phase 2: Authentication Setup ✅

- [x] Create `teleclaude/lib/auth.py` authentication module
  - Import FastAPI security classes: APIKeyHeader, APIKeyQuery, HTTPBearer ✅
  - Create query_scheme for `?apikey=` parameter ✅
  - Create header_scheme for `X-API-KEY` header ✅
  - Create bearer_scheme for `Authorization: Bearer` token ✅
  - Implement `verify_apikey()` dependency function ✅
  - Read API_KEY from `os.environ["API_KEY"]` ✅
  - Raise HTTPException(401) if key invalid or missing ✅
  - Add type hints for all functions ✅

- [x] Add API_KEY to `.env.sample`
  - Add `API_KEY=your-secret-key-here` with documentation ✅
  - Note that this is required for REST API endpoints ✅

- [x] Write unit tests in `tests/unit/test_auth.py`
  - Test valid API key (query, header, bearer) ✅
  - Test missing API key (401 response) ✅
  - Test invalid API key (401 response) ✅
  - Mock os.environ for testing ✅
  - All 9 tests passing ✅

### Phase 3: SSL Configuration ✅

- [x] Update `config.yml.sample` with SSL configuration
  - Add ssl section under rest_api ✅
  - Add enabled: true ✅
  - Add cert_file path: `${WORKING_DIR}/certs/server.crt` ✅
  - Add key_file path: `${WORKING_DIR}/certs/server.key` ✅
  - Document SSL is required for security ✅

- [x] Modify `teleclaude/daemon.py` uvicorn configuration
  - Read SSL config from config module ✅
  - Add ssl_keyfile parameter to uvicorn.Config ✅
  - Add ssl_certfile parameter to uvicorn.Config ✅
  - Only enable SSL if config.ssl.enabled is True ✅
  - Log SSL status on startup ✅

### Phase 4: REST API Endpoints ✅

- [x] Import authentication in `teleclaude/rest_api.py`
  - Add `from teleclaude.lib.auth import verify_apikey` ✅
  - Add `from typing import Annotated` ✅
  - Import `Depends` from fastapi ✅

- [x] Add `POST /api/v1/notifications` endpoint to `teleclaude/rest_api.py`
  - Add authentication: `_: Annotated[None, Depends(verify_apikey)]` as first parameter ✅
  - Input validation: session_id (required), message (required), claude_session_file (optional) ✅
  - Return success response with message_id and adapters_notified list ✅
  - Return error responses for SESSION_NOT_FOUND and SESSION_CREATION_FAILED ✅
  - Use existing `_success_response()` and `_error_response()` helpers ✅

- [x] Add session lookup/creation logic in notifications endpoint
  - Check if session exists via `await db.get_session(session_id)` ✅
  - If not exists and claude_session_file provided: create new session (TODO placeholder) ✅
  - If not exists and no claude_session_file: return 404 SESSION_NOT_FOUND ✅
  - Store claude_session_file in ux_state if provided ✅

- [x] Implement notification broadcasting in endpoint
  - Call `await adapter_client.send_message(session_id, message)` ✅
  - Capture message_id from response ✅
  - Track which adapters received the message ✅
  - Handle AdapterClient errors gracefully ✅

- [x] Set notification_sent flag after successful broadcast
  - Call `await db.set_notification_flag(session_id, True)` ✅
  - Update ux_state.claude_session_file if provided ✅
  - Log success for debugging ✅

- [x] Add `DELETE /api/v1/sessions/{session_id}/notification_flag` endpoint
  - Add authentication: `_: Annotated[None, Depends(verify_apikey)]` as first parameter ✅
  - Path parameter: session_id ✅
  - Check if session exists (return 404 if not) ✅
  - Call `await db.clear_notification_flag(session_id)` ✅
  - Return success response with flag_cleared=True ✅

### Phase 5: Wire AdapterClient to REST API ✅

- [x] Modify `teleclaude/rest_api.py` `__init__` method
  - Add `adapter_client` parameter to constructor ✅
  - Store as instance variable: `self.adapter_client = adapter_client` ✅
  - Update docstring to document new parameter ✅

- [x] Modify `teleclaude/daemon.py` REST API initialization
  - Pass `self.adapter_client` to `TeleClaudeAPI()` constructor ✅
  - Moved initialization after AdapterClient creation ✅
  - Ensure adapter_client is available before REST API starts ✅

### Phase 6: Rewrite Hook Scripts

- [ ] Rewrite `.claude/hooks/notification.py` to use HTTPS
  - Remove `bootstrap_teleclaude()` function entirely (lines 62-96)
  - Remove all TeleClaude imports: config, db, adapter_client
  - Add `requests` to script dependencies in shebang
  - Read API_KEY from `os.getenv("API_KEY")`
  - Implement HTTPS POST to `https://localhost:6666/api/v1/notifications`
  - Add `X-API-KEY` header with API key
  - Add `verify=False` to requests.post() (self-signed cert)
  - Add 5-second timeout to HTTP request
  - Return immediately after response (no blocking)
  - Handle connection errors gracefully (daemon not running)
  - Handle 401 auth errors gracefully
  - Suppress InsecureRequestWarning from urllib3

- [ ] Update `.claude/hooks/stop.py` to clear notification flag
  - Add HTTPS DELETE call to `https://localhost:6666/api/v1/sessions/{session_id}/notification_flag`
  - Add `requests` to script dependencies
  - Read API_KEY from `os.getenv("API_KEY")`
  - Add `X-API-KEY` header with API key
  - Add `verify=False` to requests.delete() (self-signed cert)
  - Add 5-second timeout
  - Keep existing TTS/summarization functionality
  - Handle errors gracefully (log and continue)
  - Handle 401 auth errors gracefully
  - Suppress InsecureRequestWarning from urllib3

### Phase 7: Testing

- [ ] Create `tests/unit/test_rest_api_notifications.py`
  - Mock AdapterClient and db dependencies
  - Test fixtures for FastAPI TestClient

- [ ] Write unit test: `test_post_notification_success`
  - Valid session exists
  - Message sent successfully via AdapterClient
  - Returns 200 with message_id

- [ ] Write unit test: `test_post_notification_creates_session`
  - Session doesn't exist
  - claude_session_file provided
  - Session created and notification sent

- [ ] Write unit test: `test_post_notification_session_not_found`
  - Session doesn't exist
  - No claude_session_file provided
  - Returns 404 SESSION_NOT_FOUND

- [ ] Write unit test: `test_post_notification_sets_flag`
  - Verify `db.set_notification_flag()` called with correct session_id
  - Verify notification_sent=True in response metadata

- [ ] Write unit test: `test_delete_notification_flag_success`
  - Session exists
  - Flag cleared successfully
  - Returns 200 with flag_cleared=True

- [ ] Write unit test: `test_delete_notification_flag_session_not_found`
  - Session doesn't exist
  - Returns 404 SESSION_NOT_FOUND

- [ ] Write unit test: `test_notification_endpoint_broadcasts_to_adapters`
  - Mock AdapterClient.send_message()
  - Verify called with correct session_id and message
  - Verify message_id returned

- [ ] Write unit test: `test_notification_endpoint_error_handling`
  - Mock AdapterClient to raise exception
  - Verify graceful error handling
  - Verify appropriate error response

- [ ] Write integration test: `test_notification_endpoint_integration`
  - Start daemon with REST API enabled
  - Create test session
  - POST notification via HTTP
  - Verify notification_sent flag set in database
  - DELETE flag via HTTP
  - Verify flag cleared

### Phase 8: Manual Testing

- [ ] Test notification endpoint with curl (HTTPS)
  ```bash
  curl -X POST https://localhost:6666/api/v1/notifications \
    --cacert certs/server.crt \
    -H "Content-Type: application/json" \
    -H "X-API-KEY: $API_KEY" \
    -d '{"session_id": "test-123", "message": "Test notification"}'
  ```
  - Verify 200 response with message_id
  - Verify notification appears in Telegram (if session exists)
  - Test without API key (expect 401)
  - Test with invalid API key (expect 401)

- [ ] Test flag clearing with curl (HTTPS)
  ```bash
  curl -X DELETE https://localhost:6666/api/v1/sessions/test-123/notification_flag \
    --cacert certs/server.crt \
    -H "X-API-KEY: $API_KEY"
  ```
  - Verify 200 response with flag_cleared=True
  - Test without API key (expect 401)

- [ ] Test notification hook script
  ```bash
  echo '{"session_id": "abc123", "message": "Test"}' | \
    uv run .claude/hooks/notification.py --notify
  ```
  - Verify completes in <100ms
  - Verify no hanging or blocking
  - Verify notification appears in Telegram

- [ ] Test stop hook script
  ```bash
  echo '{"session_id": "abc123"}' | \
    uv run .claude/hooks/stop.py --notify --summarize
  ```
  - Verify flag cleared
  - Verify TTS still works
  - Verify no hanging

- [ ] Test with live Claude Code session
  - Trigger notification event
  - Verify Claude Code remains responsive
  - Verify notification appears in Telegram
  - Verify notification_sent flag set
  - Complete task to trigger stop hook
  - Verify flag cleared

### Phase 9: Documentation & Cleanup

- [ ] Update `CLAUDE.md` with REST API usage
  - Document notification endpoint for hooks
  - Document flag management endpoints
  - Add troubleshooting section for hook issues

- [ ] Run code quality checks
  - `make format` - Format with black and isort
  - `make lint` - Run pylint and mypy
  - Fix any linting errors

- [ ] Run full test suite
  - `make test` - Run all unit and integration tests
  - Verify all tests pass
  - Verify coverage meets requirements

### Phase 7: Deployment

- [ ] Test locally with daemon restart
  - `make restart` - Restart daemon with new endpoints
  - `make status` - Verify daemon is healthy
  - Test notification endpoint with curl
  - Monitor logs: `tail -f /var/log/teleclaude.log`

- [ ] Verify REST API health
  - `curl http://localhost:6666/health`
  - Check uptime and session counts

- [ ] Create commit and deploy
  - Use `/commit-deploy` to commit and deploy to all machines
  - Verify deployment on RasPi: `ssh morriz@raspberrypi.local "cd ~/apps/TeleClaude && make status"`
  - Verify deployment on RasPi4: `ssh morriz@raspi4.local "cd ~/apps/TeleClaude && make status"`

- [ ] Verify on all machines
  - Test notification endpoint on each machine
  - Check TeleClaude daemon logs for errors
  - Verify Telegram notifications working

## Notes

### Implementation Decisions

- **Auto-create sessions**: Decided to auto-create sessions when claude_session_file is provided (enables "just-in-time" workflow)
- **Error handling**: Hooks fail silently if daemon offline (don't block Claude Code)
- **Rate limiting**: Not needed for MVP (single-user, local-only)
- **Message templates**: Pass through raw message (hook can do templating)

### Key Architecture Points

- Hooks are thin clients, daemon does the work
- REST API runs on localhost:6666 (already configured)
- AdapterClient handles broadcasting to all UI adapters
- notification_sent flag coordinated via ux_state blob

### Blockers/Issues

- None currently

## Completion Checklist

Before marking this work complete:

- [ ] All tests pass (`make test`)
- [ ] Code formatted and linted (`make format && make lint`)
- [ ] Changes deployed to all machines
- [ ] Success criteria from PRD verified:
  - [ ] Hook execution time <100ms
  - [ ] Hooks complete without hanging Claude Code
  - [ ] Notification flag coordination working
  - [ ] Messages appear in Telegram topics
- [ ] Roadmap item marked as complete in `todos/roadmap.md`
- [ ] PRD updated with actual implementation notes if needed

---

**Remember**: Use TodoWrite tool to track progress as you complete tasks!
