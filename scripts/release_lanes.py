#!/usr/bin/env python3
"""Run release inspection lanes in parallel and consolidate results.

Reads enabled agents from config.yml, runs each as a parallel lane,
then delegates to the consolidator for consensus arbitration.

Exit codes:
  0 — decision written (release authorized or not)
  1 — quorum failure or fatal error
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# Anchor at repo root and scripts dir for imports.
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (_REPO_ROOT, _SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from release_consolidator import ARBITER_PREFERENCE, load_report, resolve_consensus  # type: ignore[import-not-found]

from teleclaude.core.agents import get_enabled_agents
from teleclaude.helpers.agent_cli import _extract_json_object, _load_schema, _run_agent
from teleclaude.helpers.agent_types import AgentName, ThinkingMode


async def _run_lane(
    agent_name: str,
    prompt: str,
    schema: dict[str, object],  # guard: loose-dict - JSON schema is an arbitrary nested structure
) -> Path:
    """Run a single inspector lane and write the report file. Returns the report path."""
    report_path = Path(f"{agent_name}-report.json")
    try:
        agent = AgentName.from_str(agent_name)
        # Run the blocking subprocess in a thread to not block the event loop
        raw = await asyncio.to_thread(
            _run_agent,
            agent,
            ThinkingMode.SLOW,
            prompt,
            schema,
            tools=None,
            input_mode="stdin",
        )
        # Extract the structured result
        json_text = _extract_json_object(raw)
        parsed = json.loads(json_text)

        # Handle agent-specific response wrapping
        if isinstance(parsed, dict):
            if "structured_output" in parsed:
                parsed = parsed["structured_output"]
            elif "result" in parsed:
                result_val = parsed["result"]
                if isinstance(result_val, str):
                    parsed = json.loads(_extract_json_object(result_val))
                elif isinstance(result_val, dict):
                    parsed = result_val

        report_path.write_text(json.dumps(parsed, indent=2) + "\n", encoding="utf-8")
        print(f"  {agent_name}: classification={parsed.get('classification', '?')}")
    except Exception as exc:
        print(f"  {agent_name}: FAILED — {exc}", file=sys.stderr)
        # Write empty JSON so consolidator can detect failure
        report_path.write_text("{}\n", encoding="utf-8")

    return report_path


async def run_lanes(prompt_file: Path, schema_file: Path) -> int:
    """Run all enabled lanes in parallel, consolidate, and write decision."""
    enabled = list(get_enabled_agents())
    if not enabled:
        print("FATAL: no enabled agents in config", file=sys.stderr)
        return 1

    print(f"Enabled agents: {', '.join(enabled)}")
    print(f"Running {len(enabled)} lane(s) in parallel...")

    prompt = prompt_file.read_text(encoding="utf-8")
    schema = _load_schema(None, str(schema_file))

    # Run all lanes concurrently
    tasks = [_run_lane(agent, prompt, schema) for agent in enabled]
    report_paths = await asyncio.gather(*tasks)

    # Load reports and run consolidator
    print("\nConsolidating results...")
    reports = {}
    for path in report_paths:
        agent_name = path.stem.replace("-report", "")
        reports[agent_name] = load_report(path)

    # Filter to arbiter preference order for consensus
    enabled_set = set(enabled)
    enabled_for_consensus = [a for a in ARBITER_PREFERENCE if a in enabled_set]
    decision = resolve_consensus(reports, enabled_for_consensus)

    output_path = Path("arbiter-decision.json")
    output_path.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(decision, indent=2))

    if not decision["quorum_met"]:
        print("FATAL: quorum not met — aborting", file=sys.stderr)
        return 1

    return 0


def main() -> int:
    """CLI entrypoint."""
    import argparse

    parser = argparse.ArgumentParser(description="Run release lanes and consolidate")
    parser.add_argument("--prompt-file", type=Path, required=True, help="Path to assembled prompt")
    parser.add_argument("--schema-file", type=Path, required=True, help="Path to report schema")
    args = parser.parse_args()

    if not args.prompt_file.exists():
        print(f"FATAL: prompt file not found: {args.prompt_file}", file=sys.stderr)
        return 1
    if not args.schema_file.exists():
        print(f"FATAL: schema file not found: {args.schema_file}", file=sys.stderr)
        return 1

    return asyncio.run(run_lanes(args.prompt_file, args.schema_file))


if __name__ == "__main__":
    sys.exit(main())
