"""Merge multiple feature branches

Revision ID: 8d5d602656c2
Revises: 27d9f6638ff0, 54d931513ad1
Create Date: 2025-12-26 16:09:22.782628

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8d5d602656c2'
down_revision: Union[str, Sequence[str], None] = ('27d9f6638ff0', '54d931513ad1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
