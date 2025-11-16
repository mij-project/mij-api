from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING, Union
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .admins import Admins
    from .conversations import Conversations

class ConversationParticipants(Base):
    """会話ルーム参加者"""
    __tablename__ = "conversation_participants"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    # 旧カラム（後方互換性のため残す）
    user_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # 新カラム（participant_type: 1=user, 2=admin）
    participant_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    participant_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    role: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    last_read_message_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    notifications_muted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    conversation: Mapped["Conversations"] = relationship("Conversations")
    user: Mapped[Optional["Users"]] = relationship("Users", foreign_keys=[user_id])
    # Note: admin relationshipは外部キー制約がないため直接的なrelationshipは設定しない

    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="unique_conversation_user"),
    )

