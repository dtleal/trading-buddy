"""Q&A knowledge base: qa_entries table + seed the first entry.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-01
"""

from __future__ import annotations

from typing import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The Q&A pair that kicked this feature off — kept as the seed row so a fresh
# database (local or prod after `alembic upgrade head`) starts with it.
_SEED_QUESTION = (
    "O 5min deu uma equilibrada depois de uma queda forte. Vale a pena operar "
    "como lateralidade — comprando o fundo da Banda de Bollinger e vendendo o topo?"
)

_SEED_ANSWER = """\
Pode valer, mas com uma ressalva importante: **Bollinger em range só funciona quando a volatilidade realmente cai** — e você vinha de uma queda forte. O risco é a "equilibrada" ser só uma **pausa/pullback antes da continuação da queda**.

Checklist rápido antes de operar lateralidade:

- **Bandas estreitando** (squeeze) e preço oscilando em torno da média 20 → ok pra mean reversion. Se as bandas ainda estão abertas/inclinadas pra baixo, não é range, é tendência.
- **Topos e fundos respeitando os mesmos níveis** (2-3 toques) → confirma o range. Sem isso, é só achismo.
- **Opere com confirmação no toque da banda**, não antecipando: vela de rejeição (pavio) no topo/fundo, não entrar só porque "tocou".

Cuidado assimétrico: como a tendência maior é de queda, **a venda no topo da banda é o lado mais confiável**; a compra no fundo é contra-tendência — se for fazer, alvo curto (volta na média 20) e stop apertado abaixo do fundo da banda. Se romper a banda inferior com força, **sai na hora** — o range acabou, voltou a cair.
"""

_SEED_TAGS = ["bollinger", "lateralidade", "5min", "gestao-de-risco"]


def upgrade() -> None:
    qa_entries = op.create_table(
        "qa_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_qa_entries_updated_at", "qa_entries", ["updated_at"])

    op.bulk_insert(
        qa_entries,
        [{"question": _SEED_QUESTION, "answer": _SEED_ANSWER, "tags": _SEED_TAGS}],
    )


def downgrade() -> None:
    op.drop_table("qa_entries")
