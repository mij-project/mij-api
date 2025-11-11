"""add sample video metadata to media_assets

Revision ID: add_sample_metadata
Revises: f26f8e9a3103
Create Date: 2025-11-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'add_sample_metadata'
down_revision: Union[str, Sequence[str], None] = 'f26f8e9a3103'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # media_assetsテーブルにサンプル動画メタデータカラムを追加
    op.add_column('media_assets', sa.Column('sample_type', sa.Text(), nullable=True, comment='サンプル動画の種類: upload=アップロード, cut_out=本編から指定'))
    op.add_column('media_assets', sa.Column('sample_start_time', sa.NUMERIC(precision=10, scale=3), nullable=True, comment='本編から指定の場合の開始時間（秒）'))
    op.add_column('media_assets', sa.Column('sample_end_time', sa.NUMERIC(precision=10, scale=3), nullable=True, comment='本編から指定の場合の終了時間（秒）'))


def downgrade() -> None:
    """Downgrade schema."""
    # カラムを削除
    op.drop_column('media_assets', 'sample_end_time')
    op.drop_column('media_assets', 'sample_start_time')
    op.drop_column('media_assets', 'sample_type')
