"""merge branches: add_platformfee and remove_providers_columns

Revision ID: 2b5fb1502707
Revises: 10411d0cadbe, a238d2439d0b
Create Date: 2025-12-04 19:45:54.488000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b5fb1502707'
down_revision: Union[str, Sequence[str], None] = ('10411d0cadbe', 'a238d2439d0b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
