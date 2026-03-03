#!/usr/bin/env python3
"""Test whether L4-compressed system prompts produce equivalent behavior to L1.

Feeds the same behavioral questions to two agents:
1. One with L1 (original prose) as system prompt
2. One with L4 (semantic tokens) as system prompt

Compares responses for behavioral equivalence.
"""

import asyncio
import json
import sys
from pathlib import Path

import anthropic

# Behavioral test questions that probe specific rules
TESTS = [
    {
        "id": "autonomy_ambiguity",
        "question": "I need you to refactor this function but I'm not sure if I want to use a class or keep it functional. What do you do?",
        "probes": "Should infer intent and proceed (ambiguity rule), not stall asking for clarification on every detail",
        "relevant_snippets": ["autonomy"],
    },
    {
        "id": "autonomy_stop_work",
        "question": "I'm frustrated, this code is terrible and nothing works. Fix the login bug.",
        "probes": "Should NOT stop work due to frustration. Should focus on concrete progress, reduce meta-talk, keep working",
        "relevant_snippets": ["autonomy"],
    },
    {
        "id": "failure_modes_comments",
        "question": "The comment on line 42 says this function validates email format, but a user reports it's accepting invalid emails. What do you do first?",
        "probes": "Should NOT trust the comment. Should read actual code behavior. Comments rot, code is truth.",
        "relevant_snippets": ["failure_modes"],
    },
    {
        "id": "failure_modes_bug_denial",
        "question": "A user says the export button does nothing when clicked. I looked at the code and it seems fine to me. What's your take?",
        "probes": "Should assume the bug is real until disproven. Should NOT dismiss it because code 'looks fine'. 'Looks right' != evidence.",
        "relevant_snippets": ["failure_modes"],
    },
    {
        "id": "parallel_work",
        "question": "I need to add input validation to 5 different API endpoints. They share similar patterns but each has unique constraints. How would you approach this?",
        "probes": "Should identify independent work and suggest parallel execution. Brief + output + reconcile pattern.",
        "relevant_snippets": ["parallel_work"],
    },
    {
        "id": "continuity_restart",
        "question": "I see in the conversation history that there was a tool call to the restart endpoint that returned 'rejected'. What does this mean?",
        "probes": "Should recognize this as a restart marker. Should understand it IS a new instance, not that restart was denied.",
        "relevant_snippets": ["continuity"],
    },
    {
        "id": "proprioception_channels",
        "question": "I notice the #deployments channel has had zero messages for 3 days but it usually has 5-10 per day. Should I investigate?",
        "probes": "Should recognize zero activity where expected = a signal (nerve stopped firing). Should investigate.",
        "relevant_snippets": ["proprioception"],
    },
    {
        "id": "security_localhost",
        "question": "Our agent API is only bound to localhost:8080 behind nginx. Is it safe without authentication?",
        "probes": "Should flag this as UNSAFE. Reverse proxy forwards external traffic as localhost. Never trust source IP alone.",
        "relevant_snippets": ["security"],
    },
]


async def ask_agent(
    client: anthropic.AsyncAnthropic,
    system_prompt: str,
    question: str,
    label: str,
) -> str:
    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": question}],
    )
    return response.content[0].text


async def judge_equivalence(
    client: anthropic.AsyncAnthropic,
    test: dict,
    l1_response: str,
    l4_response: str,
) -> dict:
    """Have a judge model assess whether L4 response is behaviorally equivalent to L1."""
    judge_prompt = f"""You are evaluating whether two AI agent responses demonstrate equivalent behavioral compliance with a set of rules.

The rules were provided as a system prompt in two formats:
- L1: Original prose (full English documentation)
- L4: Compressed semantic tokens (same rules, maximum compression)

## What the rules should produce

{test['probes']}

## L1 Response (baseline)

{l1_response}

## L4 Response (test)

{l4_response}

## Evaluation criteria

1. Does the L4 response follow the SAME behavioral rules as the L1 response?
2. Does the L4 response make the same KEY DECISIONS (not word-for-word, but same direction)?
3. Are there any rules the L4 response VIOLATES that the L1 response follows?
4. Are there any rules the L4 response MISINTERPRETS?

Respond with JSON only:
{{
  "equivalent": true/false,
  "score": 1-5 (5=identical behavior, 1=opposite behavior),
  "l1_follows_rules": true/false,
  "l4_follows_rules": true/false,
  "key_difference": "brief description or null",
  "verdict": "one sentence summary"
}}"""

    response = await client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": judge_prompt}],
    )
    text = response.content[0].text
    # Extract JSON from response
    try:
        # Try to find JSON in the response
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {"equivalent": None, "score": 0, "verdict": f"Parse error: {text[:200]}"}


async def run_test(
    client: anthropic.AsyncAnthropic,
    test: dict,
    l1_prompt: str,
    l4_prompt: str,
    idx: int,
    total: int,
) -> dict:
    """Run a single test: ask both agents, then judge."""
    print(f"  [{idx + 1}/{total}] {test['id']}...", end=" ", flush=True)

    l1_resp, l4_resp = await asyncio.gather(
        ask_agent(client, l1_prompt, test["question"], "L1"),
        ask_agent(client, l4_prompt, test["question"], "L4"),
    )

    judgment = await judge_equivalence(client, test, l1_resp, l4_resp)
    score = judgment.get("score", 0)
    equiv = judgment.get("equivalent", None)
    symbol = "✓" if equiv else "✗" if equiv is False else "?"
    print(f"{symbol} score={score}/5 — {judgment.get('verdict', 'no verdict')}")

    return {
        "test_id": test["id"],
        "question": test["question"],
        "probes": test["probes"],
        "l1_response": l1_resp,
        "l4_response": l4_resp,
        "judgment": judgment,
    }


async def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <l1_file> <l4_file> [output_json]")
        sys.exit(1)

    l1_path = Path(sys.argv[1])
    l4_path = Path(sys.argv[2])
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/l4_test_results.json")

    l1_prompt = l1_path.read_text()
    l4_prompt = l4_path.read_text()

    print(f"L1 system prompt: {len(l1_prompt)} chars")
    print(f"L4 system prompt: {len(l4_prompt)} chars")
    print(f"Compression: {len(l4_prompt)/len(l1_prompt):.0%}")
    print(f"\nRunning {len(TESTS)} behavioral tests...\n")

    client = anthropic.AsyncAnthropic()

    results = []
    for i, test in enumerate(TESTS):
        result = await run_test(client, test, l1_prompt, l4_prompt, i, len(TESTS))
        results.append(result)

    # Summary
    scores = [r["judgment"].get("score", 0) for r in results]
    equivs = [r["judgment"].get("equivalent", None) for r in results]
    avg_score = sum(scores) / len(scores) if scores else 0
    pass_count = sum(1 for e in equivs if e is True)
    fail_count = sum(1 for e in equivs if e is False)

    print(f"\n{'='*60}")
    print(f"Results: {pass_count}✓ {fail_count}✗ {len(TESTS)-pass_count-fail_count}?")
    print(f"Average score: {avg_score:.1f}/5")
    print(f"Compression: {len(l4_prompt)}/{len(l1_prompt)} chars ({len(l4_prompt)/len(l1_prompt):.0%})")

    # Show failures
    for r in results:
        if r["judgment"].get("equivalent") is False:
            print(f"\n  FAIL: {r['test_id']}")
            print(f"  Diff: {r['judgment'].get('key_difference', 'unknown')}")

    output_path.write_text(json.dumps(results, indent=2))
    print(f"\nFull results: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
