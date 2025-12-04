"""update table bank_request_histories for cache external BankCodeJP response

Revision ID: 005bfb3ccdfc
Revises: e2536e20b207
Create Date: 2025-12-02 20:21:38.114326

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005bfb3ccdfc'
down_revision: Union[str, Sequence[str], None] = 'e2536e20b207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
