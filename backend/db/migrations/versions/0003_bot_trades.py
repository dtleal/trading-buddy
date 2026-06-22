"""Bot trade history: bot_trades table.

Append-only audit log of the scalper bot's own executions (opens/closes), for
future performance analysis. Manual trades are never written here.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-22
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=True),
        sa.Column("lots", sa.Float(), nullable=True),
        sa.Column("ticket", sa.BigInteger(), nullable=True),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_bot_trades_kind", "bot_trades", ["kind"])
    op.create_index("ix_bot_trades_symbol", "bot_trades", ["symbol"])
    op.create_index("ix_bot_trades_created_at", "bot_trades", ["created_at"])


def downgrade() -> None:
    op.drop_table("bot_trades")
