"""Merge multiple feature branches

Revision ID: 71b8c39a1f0a
Revises: 9590d3fe0c5f, f69109366b21
Create Date: 2026-01-09 18:38:24.591814

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '71b8c39a1f0a'
down_revision: Union[str, Sequence[str], None] = ('9590d3fe0c5f', 'f69109366b21')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
