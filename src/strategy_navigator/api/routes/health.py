"""Liveness + readiness."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from strategy_navigator.__about__ import __version__
from strategy_navigator.db.engine import get_engine
from strategy_navigator.stages import ported_workflows

router = APIRouter()


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/readyz")
async def readyz() -> dict[str, object]:
    checks: dict[str, object] = {"version": __version__}
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        return checks
    checks["status"] = "ready"
    checks["ported_workflows"] = [str(w) for w in ported_workflows()]
    return checks
