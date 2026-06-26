---
description: Antigravity CLI quota and usage retrieval research for TeleClaude dispatch decisions.
---

# Antigravity CLI Quota Research

## Overview

Antigravity CLI (`agy`) quota collection uses an observed local language-server endpoint exposed by a short-lived CLI session. TeleClaude treats the behavior as local empirical research, not as a publicly documented vendor contract.

## Source classification

These findings are own research from local CLI, log, and local-RPC behavior. No authoritative public vendor documentation for this quota retrieval path is known in the repository's third-party docs, so collectors must treat the behavior as observed and verify failures explicitly.

## Findings

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

## Tested local-RPC flow

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

## Recommended collector shape

Start a short-lived `agy` session with an isolated log file, wait until the HTTP port appears in that log, call the local quota summary endpoint, normalize `remainingFraction` and `resetTime` by bucket/window, and immediately end the session. This avoids interpreting TUI text and avoids sending `/usage` as a prompt.

## Caveats

- The runner must always clean up the temporary tmux session, including failure paths.
- The local endpoint is available only while `agy` is running.
- Do not log access tokens or raw auth files. The local endpoint requires no bearer token because it is exposed by the already-authenticated local runtime.
- If `remainingFraction` is absent or a bucket is disabled, record a probe failure or disabled bucket rather than inventing a fallback percentage.
