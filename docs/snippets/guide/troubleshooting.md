---
id: teleclaude/guide/troubleshooting
type: guide
scope: project
description: High-level troubleshooting workflow for daemon and adapter issues.
requires: []
---

Guide
- Check daemon status with make status and review logs via instrukt-ai-logs.
- Confirm bot permissions and trusted_bots whitelist if Telegram commands fail.
- Verify Redis connectivity when cross-computer operations fail.
- Use make restart for controlled restarts; avoid make stop unless emergency.
