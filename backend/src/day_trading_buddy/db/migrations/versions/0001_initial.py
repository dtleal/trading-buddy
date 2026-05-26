"""Initial schema: market_snapshots, economic_events, news_items, bias_reports, llm_outputs.

Revision ID: 0001
Revises:
Create Date: 2026-05-26
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("ma200_d", sa.Float(), nullable=True),
        sa.Column("ma200_h4", sa.Float(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_market_snapshots_symbol", "market_snapshots", ["symbol"])
    op.create_index("ix_market_snapshots_timestamp", "market_snapshots", ["timestamp"])
    op.create_index("ix_market_snapshots_symbol_ts", "market_snapshots", ["symbol", "timestamp"])

    op.create_table(
        "economic_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("impact", sa.String(length=16), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast", sa.String(length=64), nullable=True),
        sa.Column("previous", sa.String(length=64), nullable=True),
        sa.Column("actual", sa.String(length=64), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="forexfactory"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_economic_events_scheduled_at", "economic_events", ["scheduled_at"])
    op.create_index(
        "ix_economic_events_name_scheduled",
        "economic_events",
        ["name", "scheduled_at"],
        unique=True,
    )

    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("sentiment_label", sa.String(length=16), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_news_items_source", "news_items", ["source"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])

    op.create_table(
        "bias_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("asset", sa.String(length=16), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_bias_reports_asset", "bias_reports", ["asset"])
    op.create_index("ix_bias_reports_timestamp", "bias_reports", ["timestamp"])
    op.create_index("ix_bias_reports_asset_ts", "bias_reports", ["asset", "timestamp"])

    op.create_table(
        "llm_outputs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_llm_outputs_kind", "llm_outputs", ["kind"])
    op.create_index("ix_llm_outputs_prompt_hash", "llm_outputs", ["prompt_hash"])
    op.create_index("ix_llm_outputs_created_at", "llm_outputs", ["created_at"])


def downgrade() -> None:
    op.drop_table("llm_outputs")
    op.drop_table("bias_reports")
    op.drop_table("news_items")
    op.drop_table("economic_events")
    op.drop_table("market_snapshots")
