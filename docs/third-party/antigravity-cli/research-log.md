---
description: Antigravity CLI local research log for TeleClaude dispatch decisions.
---

# Antigravity CLI Research Log

## Antigravity Local Language Server Quota Summary

_Timestamp: 2026-06-26T14:46:44+02:00_

### Objective

Determine how TeleClaude can collect Gemini/Antigravity five-hour and weekly quota state without screen-scraping `/usage` or sending `/usage` to the model.

### Answer

Antigravity CLI (`agy`) quota collection uses an observed local language-server endpoint exposed by a short-lived CLI session. Treat the path as local empirical behavior, not a public vendor contract. Start a short-lived `agy` session with an isolated log file, wait until the HTTP port appears in that log, call the local quota summary endpoint, normalize `remainingFraction` and `resetTime` by bucket/window, and immediately end the session.

### Evidence

- `agy --print '/usage'` does not execute the TUI slash command. It sends `/usage` as ordinary model input and can consume a model turn.
- `agy models` lists available models only; it does not expose quota state.
- Starting `agy` launches a local language server bound to localhost and writes the HTTP port to the CLI log.
- The local language server exposes a structured quota endpoint:
  `POST /exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary`.
- The endpoint accepts an empty JSON object and returns quota groups and buckets with stable fields observed locally:
  - `displayName`
  - `bucketId`
  - `window`
  - `remainingFraction`
  - `resetTime`
- The observed response included Gemini model buckets for `weekly` and `5h`, plus separate third-party model buckets.
- Directly calling the Google backend quota endpoint with the access token stored on disk returned `401 invalid_token`; the CLI refreshes auth through its runtime/keyring path.

Tested local-RPC flow:

```bash
log=$(mktemp)

tmux new-session -d -s teleclaude_agy_quota -x 120 -y 40 \
  "agy --log-file '$log'"

port=$(
  rg -o 'random port at ([0-9]+) for HTTP' -r '$1' "$log" \
    | tail -1
)

curl -sS -X POST \
  "http://localhost:$port/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary" \
  -H 'Content-Type: application/json' \
  --data '{}'

tmux kill-session -t teleclaude_agy_quota
```

### Gaps

- The runner must always clean up the temporary tmux session, including failure paths.
- The local endpoint is available only while `agy` is running.
- Do not log access tokens or raw auth files. The local endpoint requires no bearer token because it is exposed by the already-authenticated local runtime.
- If `remainingFraction` is absent or a bucket is disabled, record a probe failure or disabled bucket rather than inventing a fallback percentage.
