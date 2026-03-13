"""Handlers for telec events and signals commands."""
from __future__ import annotations

from teleclaude.cli.telec.help import _usage



__all__ = [
    "_handle_events",
    "_handle_events_list",
    "_handle_signals",
    "_handle_signals_status",
]

def _handle_events(args: list[str]) -> None:
    """Handle telec events subcommands."""
    if not args:
        print(_usage("events"))
        return

    subcommand = args[0]
    if subcommand == "list":
        _handle_events_list(args[1:])
    else:
        print(f"Unknown events subcommand: {subcommand}")
        print(_usage("events"))
        raise SystemExit(1)


def _handle_events_list(args: list[str]) -> None:
    """List all registered event schemas."""
    from teleclaude.events import build_default_catalog

    domain_filter: str | None = None
    i = 0
    while i < len(args):
        if args[i] == "--domain" and i + 1 < len(args):
            domain_filter = args[i + 1]
            i += 2
        else:
            i += 1

    catalog = build_default_catalog()
    schemas = catalog.list_all()
    if domain_filter:
        schemas = [s for s in schemas if s.domain == domain_filter]

    if not schemas:
        print("No event schemas found.")
        return

    col_widths = [55, 8, 24, 8, 50, 12]
    headers = ["EVENT TYPE", "LEVEL", "DOMAIN", "VISIBLE", "DESCRIPTION", "ACTIONABLE"]
    header_row = "  ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(header_row)
    print("-" * (sum(col_widths) + 2 * (len(col_widths) - 1)))
    for s in schemas:
        row = "  ".join(
            [
                str(s.event_type).ljust(col_widths[0]),
                str(s.default_level).ljust(col_widths[1]),
                str(s.domain).ljust(col_widths[2]),
                str(s.default_visibility.value).ljust(col_widths[3]),
                str(s.description).ljust(col_widths[4]),
                ("yes" if s.actionable else "no").ljust(col_widths[5]),
            ]
        )
        print(row)


def _handle_signals(args: list[str]) -> None:
    """Handle telec signals subcommands."""
    if not args or args[0] == "status":
        _handle_signals_status()
    else:
        print(f"Unknown signals subcommand: {args[0]}")
        print(_usage("signals"))
        raise SystemExit(1)


def _handle_signals_status() -> None:
    """Show signal pipeline item/cluster/synthesis counts and last ingest time."""
    import asyncio  # pylint: disable=import-outside-toplevel

    async def _query() -> None:
        import aiosqlite  # pylint: disable=import-outside-toplevel

        from teleclaude.config import config  # pylint: disable=import-outside-toplevel
        from teleclaude.events.signal.db import SignalDB  # pylint: disable=import-outside-toplevel

        db_path = config.database.path
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            sdb = SignalDB(conn)
            try:
                counts = await sdb.get_signal_counts()
                last_ingest = await sdb.get_last_ingest_time()
            except Exception:  # pylint: disable=broad-exception-caught
                print("Signal tables not initialized. Start the daemon to enable signal ingestion.")
                return

        print("Signal Pipeline Status")
        print("----------------------")
        print(f"Items ingested:  {counts['items']}")
        print(f"Clusters formed: {counts['clusters']}")
        print(f"Syntheses ready: {counts['syntheses']}")
        print(f"Pending cluster: {counts['pending']}")
        print(f"Last ingest:     {last_ingest or 'never'}")

    asyncio.run(_query())
