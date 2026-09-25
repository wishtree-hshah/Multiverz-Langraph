"""Re-enqueue dead-lettered runs.

uv run python scripts/replay_dead_letter.py                 # all unreplayed
uv run python scripts/replay_dead_letter.py --workflow report_render
uv run python scripts/replay_dead_letter.py --id 42
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt

from strategy_navigator.constants import Workflow
from strategy_navigator.db.engine import session_scope
from strategy_navigator.db.models import DeadLetter
from strategy_navigator.db.repositories import DeadLetterRepository, RunRepository
from strategy_navigator.logging import configure_logging, get_logger
from strategy_navigator.queue.app import app as queue_app
from strategy_navigator.queue.tasks import enqueue_run

log = get_logger("replay")


async def _run(workflow: str | None, only_id: int | None, limit: int) -> None:
    configure_logging()
    async with queue_app.open_async():
        async with session_scope() as s:
            rows = await DeadLetterRepository(s).list_unreplayed(limit)
        if only_id is not None:
            rows = [r for r in rows if r.id == only_id]
        if workflow:
            rows = [r for r in rows if r.workflow == workflow]

        for r in rows:
            async with session_scope() as s:
                run = await RunRepository(s).get(r.run_id)
            await enqueue_run(
                run_id=r.run_id,
                session_id=r.session_id,
                workflow=Workflow(r.workflow),
                project_id=run.project_id if run else None,
                request=r.payload,
                callback_url=run.callback_url if run else None,
            )
            async with session_scope() as s:
                dl = await s.get(DeadLetter, r.id)
                if dl:
                    dl.replayed_at = dt.datetime.now(dt.UTC)
            log.info("replay.enqueued", run_id=r.run_id, workflow=r.workflow)

        log.info("replay.done", count=len(rows))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflow")
    ap.add_argument("--id", type=int)
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    asyncio.run(_run(args.workflow, args.id, args.limit))
