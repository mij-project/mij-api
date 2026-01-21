"""merge heads

Revision ID: 370a76025981
Revises: 14a1cc314d82, 8061b2f273ad
Create Date: 2026-01-21 11:53:29.045781

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '370a76025981'
down_revision: Union[str, Sequence[str], None] = ('14a1cc314d82', '8061b2f273ad')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
