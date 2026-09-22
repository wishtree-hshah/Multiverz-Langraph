"""``strategy-navigator`` CLI — one binary, several roles.

strategy-navigator serve                 # the FastAPI app
strategy-navigator worker --lane short    # a lane worker (short|long|retry)
strategy-navigator db upgrade             # alembic + procrastinate + checkpointer schema
strategy-navigator db downgrade -1
strategy-navigator workflows              # list workflows and porting status
strategy-navigator eval                   # run stage quality evals
"""

from __future__ import annotations

import asyncio

import typer

from strategy_navigator.config import settings
from strategy_navigator.constants import Lane
from strategy_navigator.logging import configure_logging, get_logger

cli = typer.Typer(add_completion=False, help="Strategy Navigator orchestration CLI")
db_app = typer.Typer(help="Database schema management")
cli.add_typer(db_app, name="db")
prompts_app = typer.Typer(help="Prompt template management (Mongo export / audit)")
cli.add_typer(prompts_app, name="prompts")

log = get_logger("cli")


@cli.command()
def serve(
    host: str = typer.Option(settings.api_host),
    port: int = typer.Option(settings.api_port),
    reload: bool = typer.Option(False, help="uvicorn autoreload (dev only)"),
) -> None:
    """Run the HTTP API (webhooks + run status/resume)."""
    import uvicorn

    configure_logging()
    uvicorn.run(
        "strategy_navigator.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_config=None,
        access_log=False,
    )


@cli.command()
def worker(
    lane: Lane = typer.Option(..., help="short | long | retry"),
    concurrency: int = typer.Option(None, help="override lane default"),
) -> None:
    """Run a queue worker for one lane."""
    from strategy_navigator.observability import setup_tracing
    from strategy_navigator.queue.app import app as queue_app
    from strategy_navigator.queue.lanes import concurrency_for_lane, queues_for_lane

    configure_logging()
    setup_tracing()
    queues = queues_for_lane(lane)
    conc = concurrency or concurrency_for_lane(lane)
    log.info("worker.start", lane=str(lane), queues=queues, concurrency=conc)

    async def _run() -> None:
        async with queue_app.open_async():
            await queue_app.run_worker_async(queues=queues, concurrency=conc, wait=True)

    asyncio.run(_run())


@db_app.command("upgrade")
def db_upgrade(revision: str = typer.Argument("head")) -> None:
    """Apply alembic migrations, then install procrastinate + LangGraph checkpointer schema."""
    from alembic import command
    from alembic.config import Config

    from strategy_navigator.graph.checkpointer import setup_checkpointer
    from strategy_navigator.queue.app import app as queue_app

    configure_logging()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.sqlalchemy_url)
    command.upgrade(cfg, revision)
    log.info("db.alembic_done", revision=revision)

    async def _rest() -> None:
        async with queue_app.open_async():
            # procrastinate's own apply_schema_async() is not idempotent (plain
            # CREATE TYPE/TABLE, no IF NOT EXISTS) and raises DuplicateObject on
            # a second run — which every subsequent `docker compose up` triggers
            # via the one-shot `migrate` service. Skip if already installed.
            already = await queue_app.connector.execute_query_one_async(
                "SELECT to_regclass('public.procrastinate_jobs') IS NOT NULL AS exists"
            )
            if already["exists"]:
                log.info("db.procrastinate_schema_already_applied")
            else:
                await queue_app.schema_manager.apply_schema_async()
        await setup_checkpointer()

    asyncio.run(_rest())
    log.info("db.upgrade_complete")


@db_app.command("downgrade")
def db_downgrade(revision: str = typer.Argument("-1")) -> None:
    from alembic import command
    from alembic.config import Config

    configure_logging()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", settings.sqlalchemy_url)
    command.downgrade(cfg, revision)


@cli.command()
def workflows() -> None:
    """List workflows, their lane, and whether they are ported off the stub."""
    from rich.console import Console
    from rich.table import Table

    from strategy_navigator.constants import WORKFLOW_LANE, Workflow
    from strategy_navigator.stages import is_ported

    table = Table(title="Strategy Navigator workflows")
    table.add_column("workflow")
    table.add_column("lane")
    table.add_column("status")
    for wf in Workflow:
        table.add_row(
            str(wf),
            str(WORKFLOW_LANE.get(wf, "-")),
            "[green]ported[/]" if is_ported(wf) else "[yellow]stub[/]",
        )
    Console().print(table)


@prompts_app.command("pull")
def prompts_pull(
    mongo_url: str = typer.Option(None, help="mongodb://... ($SN_N8N_MONGO_URL)"),
    db: str = typer.Option(None, help="Mongo database name ($SN_N8N_MONGO_DB)"),
    from_backend: bool = typer.Option(False, help="use GET {backend}/n8n/prompts instead of Mongo"),
    backend_url: str = typer.Option(None),
    token: str = typer.Option(None),
    check: bool = typer.Option(False, help="report only; non-zero exit if a template is missing"),
) -> None:
    """Export the stage prompt templates from the n8n MongoDB into prompts/_mongo/."""
    from strategy_navigator.prompts.pull import main as pull_main

    argv: list[str] = []
    if mongo_url:
        argv += ["--mongo-url", mongo_url]
    if db:
        argv += ["--db", db]
    if from_backend:
        argv += ["--from-backend"]
    if backend_url:
        argv += ["--backend-url", backend_url]
    if token:
        argv += ["--token", token]
    if check:
        argv += ["--check"]
    raise typer.Exit(pull_main(argv))


@prompts_app.command("audit")
def prompts_audit() -> None:
    """Show every prompt ref, its n8n source, and what would be used at runtime."""
    from rich.console import Console
    from rich.table import Table

    from strategy_navigator.prompts import prompt_source, registry

    table = Table(title="Strategy Navigator prompts")
    table.add_column("ref")
    table.add_column("n8n source")
    table.add_column("promptId")
    table.add_column("resolves to")
    for ref, spec in sorted(registry.PROMPTS.items()):
        resolved = prompt_source(ref)
        colour = {
            "inline": "green",
            "mongo-export": "green",
            "local-draft": "yellow",
            "missing": "red",
        }.get(resolved, "white")
        table.add_row(
            ref,
            spec.source.value,
            spec.prompt_id or "-",
            f"[{colour}]{resolved}[/]",
        )
    Console().print(table)


@cli.command()
def eval() -> None:  # noqa: A001 - deliberately mirrors the make target name
    """Run stage quality evals (evals/run_evals.py)."""
    import runpy

    configure_logging()
    runpy.run_path("evals/run_evals.py", run_name="__main__")


if __name__ == "__main__":
    cli()
