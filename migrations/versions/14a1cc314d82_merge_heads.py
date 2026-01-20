"""merge heads

Revision ID: 14a1cc314d82
Revises: 1c5169229dda, ab0331a16e84
Create Date: 2026-01-16 20:59:17.592167

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14a1cc314d82'
down_revision: Union[str, Sequence[str], None] = ('1c5169229dda', 'ab0331a16e84')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
