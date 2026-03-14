#!/usr/bin/env python3
"""Safety check - ensure no production sessions before running tests."""

import sqlite3
import sys
from pathlib import Path

# Check production database
db_path = Path(__file__).parent.parent / "teleclaude.db"
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM sessions")
    row = cursor.fetchone()
    count = int(row[0]) if row is not None else 0
    conn.close()

    if count > 0:
        print(f"ERROR: {count} active production sessions found!")
        print("Running tests will DESTROY your production sessions.")
        print("Close all sessions first or run tests in Docker.")
        sys.exit(1)

print("✓ Safe to run tests (no active production sessions)")
