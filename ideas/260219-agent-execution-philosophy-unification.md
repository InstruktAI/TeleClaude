# Idea: Unify Agent Execution Philosophy into Consolidated Decision Record

## Problem

Multiple overlapping memories describe agent execution discipline scattered across different frames:

- ID 19: Commit without asking (permission-seeking breaks flow)
- ID 12: Execute through hurdles, no noise (act fast, promote to todo if >5min)
- ID 10: Five-minute execution threshold (inline vs todo boundary)
- ID 11: Bug hunting philosophy (always hunt, never defer)
- ID 35: No multiple choice (plain conversation preference)

These form a coherent philosophy but are fragmented across the memory database, making them harder to discover and apply consistently.

## Observation

- Each memory independently reinforces a discipline principle
- The principles are interdependent: five-minute rule informs commit-without-asking
- Agents reacting to fragments rather than unified philosophy leads to inconsistent execution
- User frustration (ID 19) indicates the principle is not being internalized

## Opportunity

Create a consolidated **Agent Execution Discipline** decision record that:

1. Unifies the five-minute threshold, bug-hunting, execution-without-asking principles
2. Explains the philosophy: act > ask, fast feedback > permission, inline > defer
3. Provides decision tree: when to inline, when to todo, when to commit
4. Serves as baseline instruction for new agent initialization

This becomes a reference document that supersedes the scattered memories.

## Related Principles

- Autonomy policy (default: act for safe, reversible, in-scope actions)
- Heartbeat policy (temporal self-awareness during sustained work)
- Execution philosophy from CLAUDE.md

## Estimated Value

Medium. Clarifies expectations and provides a decision reference, but behavior change requires reinforcement.

## Risks

- Written principles alone don't change behavior (memory alone isn't enforcement)
- Requires integration into agent system prompts or skill workflows
- May conflict with project-specific execution models

## Next Steps

1. Synthesize the five discipline memories into a single document
2. Add decision tree and examples
3. Test with next agent initialization
4. Consider promotion to baseline system prompt
