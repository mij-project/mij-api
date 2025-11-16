"""add_admin_support_to_conversations

Revision ID: 8929fff7ea48
Revises: fe21859d00e6
Create Date: 2025-11-15 19:10:10.880238

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8929fff7ea48'
down_revision: Union[str, Sequence[str], None] = 'fe21859d00e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # conversation_messagesテーブルに sender_admin_id カラムを追加
    op.add_column('conversation_messages',
                  sa.Column('sender_admin_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_conversation_messages_sender_admin_id',
                         'conversation_messages', 'admins', ['sender_admin_id'], ['id'])

    # conversation_participantsテーブルに participant_id と participant_type カラムを追加
    op.add_column('conversation_participants',
                  sa.Column('participant_id', sa.dialects.postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('conversation_participants',
                  sa.Column('participant_type', sa.SmallInteger(), nullable=True))

    # 既存データのマイグレーション: user_id を participant_id にコピーし、participant_type を 1 (user) に設定
    op.execute("""
        UPDATE conversation_participants
        SET participant_id = user_id, participant_type = 1
        WHERE user_id IS NOT NULL
    """)

    # participant_type を NOT NULL に変更
    op.alter_column('conversation_participants', 'participant_type', nullable=False)

    # user_id を nullable に変更（将来的に削除する可能性があるため）
    op.alter_column('conversation_participants', 'user_id', nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # conversation_participantsテーブルの変更を元に戻す
    op.alter_column('conversation_participants', 'user_id', nullable=False)
    op.drop_column('conversation_participants', 'participant_type')
    op.drop_column('conversation_participants', 'participant_id')

    # conversation_messagesテーブルの変更を元に戻す
    op.drop_constraint('fk_conversation_messages_sender_admin_id', 'conversation_messages', type_='foreignkey')
    op.drop_column('conversation_messages', 'sender_admin_id')
