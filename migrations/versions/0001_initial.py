"""initial app tables: sn_run, sn_search_cache, sn_dead_letter, sn_token_usage

Revision ID: 0001
Revises:
Create Date: 2026-09-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sn_run",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("workflow", sa.String(64), nullable=False, index=True),
        sa.Column("lane", sa.String(16), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=True, index=True),
        sa.Column("voting_session_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued", index=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("callback_url", sa.Text(), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("interrupt_payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sn_run_workflow_status", "sn_run", ["workflow", "status"])

    op.create_table(
        "sn_search_cache",
        sa.Column("query_hash", sa.String(64), primary_key=True),
        sa.Column("op", sa.String(16), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )

    op.create_table(
        "sn_dead_letter",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), nullable=False, index=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("workflow", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(128), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("traceback", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "sn_token_usage",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(64), nullable=False, index=True),
        sa.Column("session_id", sa.String(64), nullable=False, index=True),
        sa.Column("workflow", sa.String(64), nullable=False, index=True),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("model", sa.String(64), nullable=False, index=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("sn_token_usage")
    op.drop_table("sn_dead_letter")
    op.drop_table("sn_search_cache")
    op.drop_index("ix_sn_run_workflow_status", table_name="sn_run")
    op.drop_table("sn_run")
