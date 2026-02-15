---
id: 'project/spec/tools/escalation'
type: 'spec'
scope: 'project'
description: 'Contract for the teleclaude__escalate MCP tool.'
audience:
  - help-desk
---

# Escalation Tool — Spec

## Required reads

## What it is

The `teleclaude__escalate` MCP tool creates a Discord thread in the escalation forum, sets the session to relay mode, and notifies admins.

## Canonical fields

- Tool name: `teleclaude__escalate`
- Parameters:
  - `customer_name` (required, string): Display name of the customer
  - `reason` (required, string): Why escalation is needed
  - `context_summary` (optional, string): Relevant conversation context
- Return: Confirmation message with thread ID
- Side effects:
  - Creates a Discord thread in the escalation forum channel
  - Sets `relay_status = "active"` on the session
  - Forwards subsequent customer messages to the relay thread
  - Sends admin notification

## See also
