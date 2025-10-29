"""add reject_comments to posts and media_assets

Revision ID: 20251029175607
Revises: dfc424e8f8be
Create Date: 2025-10-29 17:56:07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '20251029175607'
down_revision: Union[str, Sequence[str], None] = 'dfc424e8f8be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # postsテーブルにreject_commentsカラムを追加
    op.add_column('posts', sa.Column('reject_comments', sa.Text(), nullable=True))

    # media_assetsテーブルにreject_commentsカラムを追加
    op.add_column('media_assets', sa.Column('reject_comments', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # postsテーブルからreject_commentsカラムを削除
    op.drop_column('posts', 'reject_comments')

    # media_assetsテーブルからreject_commentsカラムを削除
    op.drop_column('media_assets', 'reject_comments')
