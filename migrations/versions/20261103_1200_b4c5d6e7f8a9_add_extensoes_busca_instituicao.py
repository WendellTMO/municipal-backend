"""add extensoes unaccent e pg_trgm para a busca de instituições

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-11-03 12:00:00.000000+00:00
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic
revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, None] = "a3b4c5d6e7f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade database schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    """Downgrade database schema."""
    # As extensões ficam: outra consulta pode depender delas e removê-las não devolve nada.
