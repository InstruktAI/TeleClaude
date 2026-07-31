---
description: SQLAlchemy 2.0 connection-pool defaults for SQLite, including the 2.0.38 change from NullPool to QueuePool for file-based databases and the aiosqlite dialect's per-database-type behavior.
---

# SQLAlchemy SQLite Connection Pooling

## What it is

How SQLAlchemy 2.0 pools connections for SQLite, which pool class each database
type selects by default, and what the dialect configures on the DBAPI connection.
Relevant wherever a SQLite engine is constructed without an explicit `poolclass`.

## Default pool class by dialect and database type

| Dialect                    | Database type | Default pool            |
| -------------------------- | ------------- | ----------------------- |
| `sqlite+pysqlite` (sync)   | File          | `QueuePool`             |
| `sqlite+pysqlite` (sync)   | `:memory:`    | `SingletonThreadPool`   |
| `sqlite+aiosqlite` (async) | File          | `AsyncAdaptedQueuePool` |
| `sqlite+aiosqlite` (async) | `:memory:`    | `StaticPool`            |

For file-based databases the aiosqlite dialect defaults to
`AsyncAdaptedQueuePool`, "which replaces the NullPool default used in versions
prior to 2.0.38". For in-memory databases it defaults to `StaticPool` so all
access reaches the same memory database through a single connection.

`QueuePool` is described as the default pooling implementation for all `Engine`
objects other than SQLite with a `:memory:` database, and is documented as not
compatible with asyncio — the async equivalent is `AsyncAdaptedQueuePool`.

## The 2.0.38 default change

The SQLAlchemy 2.0 changelog records the change directly:

> The SQLite dialect now defaults to using `QueuePool` instead of `NullPool` for
> file-based databases, while setting the `check_same_thread` parameter to
> `False`. This change addresses measurable negative performance impacts caused
> by not holding onto database connections. The pool class remains customizable
> via engine configuration.

Two consequences follow for any code that pins `poolclass=NullPool` on a
file-based SQLite engine:

- It opts out of the upstream default and re-adopts the behavior the change was
  made to remove.
- Because the dialect sets `check_same_thread=False` alongside pooling, a pooled
  SQLite connection is not thread-pinned by the dialect's own configuration.

## Pool sizing semantics

`QueuePool.__init__(creator, pool_size=5, max_overflow=10, timeout=30.0, use_lifo=False, **kw)`:

- `pool_size` — connections the pool maintains. Default 5. `0` means no limit.
- `max_overflow` — connections permitted beyond `pool_size` during a burst.
  Default 10. `-1` means no overflow limit.
- `timeout` — seconds a checkout waits before giving up. Default 30.0.
- `use_lifo` — retrieve last-in-first-out instead of FIFO. Default `False`.

## When NullPool is the documented choice

`NullPool` remains documented for file-based SQLite as a way to prevent file
locking issues, at the cost of a stated small performance overhead:

```python
from sqlalchemy import NullPool

engine = create_engine("sqlite:///myfile.db", poolclass=NullPool)
```

`StaticPool` is documented for single-connection memory databases, where it
forces every checkout to return the same DBAPI connection; it does not support
concurrency and suits fully serialized access such as a single-threaded test
suite.

## Sources

- https://docs.sqlalchemy.org/en/20/dialects/sqlite.html — dialect pooling behavior, aiosqlite per-database-type defaults, NullPool and StaticPool guidance.
- https://docs.sqlalchemy.org/en/20/core/pooling.html — `QueuePool` API and sizing parameters.
- https://docs.sqlalchemy.org/en/20/changelog/changelog_20.html — the 2.0.38 SQLite default pool change.
- https://context7.com/websites/sqlalchemy_en_20/llms.txt
