"""App-owned tables.

Deliberately small — LangGraph state lives in its own checkpoint tables, the
queue lives in procrastinate's. These four track the things we need to query
operationally:

* ``sn_run``           — one row per workflow run; lifecycle, attempts, timings
* ``sn_search_cache``  — Jina results keyed by query hash (survives retries)
* ``sn_dead_letter``   — runs that exhausted ``SN_RUN_MAX_ATTEMPTS``
* ``sn_token_usage``   — per-call model spend (replaces the n8n Token Counter)
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"  # paused at a LangGraph interrupt()
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # will be retried
    DEAD = "dead"  # exhausted attempts -> dead-letter


class RunRecord(Base):
    __tablename__ = "sn_run"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    workflow: Mapped[str] = mapped_column(String(64), index=True)
    lane: Mapped[str] = mapped_column(String(16))
    project_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    voting_session_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    status: Mapped[str] = mapped_column(String(24), default=RunStatus.QUEUED, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    callback_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    request_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    interrupt_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_sn_run_workflow_status", "workflow", "status"),)


class SearchCache(Base):
    __tablename__ = "sn_search_cache"

    query_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    op: Mapped[str] = mapped_column(String(16))  # "search" | "read"
    query: Mapped[str] = mapped_column(Text)
    response: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), index=True)


class DeadLetter(Base):
    __tablename__ = "sn_dead_letter"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    workflow: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer)
    error_type: Mapped[str] = mapped_column(String(128))
    error_message: Mapped[str] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    replayed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TokenUsage(Base):
    __tablename__ = "sn_token_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    workflow: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64), index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
