#!/usr/bin/env -S uv run --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "instruktai-python-logger",
#     "python-dotenv",
#     "pydantic",
#     "pyyaml",
#     "aiohttp",
#     "dateparser",
#     "munch",
# ]
# ///

"""Search native agent session transcripts (~/.claude, ~/.codex, ~/.gemini)."""

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.history.search import (  # noqa: E402
    display_combined_history,
    parse_agents,
    show_transcript,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search native agent session transcripts.")
    parser.add_argument("--agent", required=True, help="Agent name(s) (claude,codex,gemini) or 'all'.")
    parser.add_argument("--show", metavar="SESSION_ID", help="Show full parsed transcript for a session.")
    parser.add_argument("--thinking", action="store_true", help="Include thinking blocks in --show output.")
    parser.add_argument(
        "--tail", type=int, default=0, help="Limit output to last N chars (0=unlimited, default for --show)."
    )
    parser.add_argument("terms", nargs=argparse.REMAINDER, help="Search terms.")
    args = parser.parse_args()

    selected_agents = parse_agents(args.agent)

    if args.show:
        show_transcript(selected_agents, args.show, tail_chars=args.tail, include_thinking=args.thinking)
        return

    search_term = " ".join(args.terms).strip()
    if not search_term:
        print("Search terms are required. Example: history.py --agent all <terms>")
        sys.exit(1)

    display_combined_history(selected_agents, search_term)


if __name__ == "__main__":
    main()
