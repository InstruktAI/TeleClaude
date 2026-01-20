---
id: teleclaude/checklist/multi-computer-readiness
type: checklist
scope: project
description: Readiness checklist for multi-computer TeleClaude deployments.
requires:
  - ../guide/multi-computer-setup.md
---

Checklist
- Each computer has a unique bot token and computer name.
- All bots are in the same supergroup with Topics enabled.
- All bots have Manage Topics permissions.
- trusted_bots list includes every bot on every computer.
- Exactly one bot is configured as telegram.is_master.
- make status shows each daemon running.
- teleclaude__list_computers returns all online machines.
- If using MCP across computers, Redis is configured and reachable on all hosts.
