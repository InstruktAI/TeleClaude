# Global agent artifacts configuration & distribution

This folder harbors agent artifact definitions and tooling to build and distribute artifacts to multiple AI agents (Claude Code, Codex, Gemini).

## Required reads

@docs/project/procedure/agent-artifact-distribution.md
@docs/project/policy/agent-artifact-governance.md

## Tools

### history.py — Search session transcripts

Searches through native transcript files for conversations matching a search term. Use when the user asks to find a previous conversation, recall what was discussed, or locate a session to resume.

Usage: `~/.teleclaude/scripts/history.py --agent {{agent}} <search terms>`

- Search terms are required
- Returns matching sessions with project name, context snippet, and session ID
