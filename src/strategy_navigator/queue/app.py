"""The procrastinate application (Postgres-backed job queue — no Redis).

One ``App``; workers subscribe to a subset of its queues per lane. The schema is
installed by ``strategy-navigator db upgrade``.
"""

from __future__ import annotations

from procrastinate import App, PsycopgConnector

from strategy_navigator.config import settings

app = App(
    connector=PsycopgConnector(conninfo=settings.psycopg_url),
    import_paths=["strategy_navigator.queue.tasks"],
)
