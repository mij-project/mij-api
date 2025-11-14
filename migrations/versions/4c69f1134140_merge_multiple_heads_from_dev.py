"""Merge multiple heads from dev

Revision ID: 4c69f1134140
Revises: 9ddde6fa373c, be39fb48fcc5
Create Date: 2025-11-14 11:57:01.446586

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c69f1134140'
down_revision: Union[str, Sequence[str], None] = ('9ddde6fa373c', 'be39fb48fcc5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
