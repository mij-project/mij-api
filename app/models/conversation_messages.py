from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .admins import Admins
    from .conversations import Conversations
    from .message_assets import MessageAssets

class ConversationMessages(Base):
    """会話ルームメッセージ"""
    __tablename__ = "conversation_messages"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False)
    sender_user_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    sender_admin_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("admins.id"), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=True, default=1)
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_message_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("conversation_messages.id"), nullable=True)
    moderation: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    conversation: Mapped["Conversations"] = relationship("Conversations")
    sender_user: Mapped[Optional["Users"]] = relationship("Users", foreign_keys=[sender_user_id])
    sender_admin: Mapped[Optional["Admins"]] = relationship("Admins", foreign_keys=[sender_admin_id])
    message_assets: Mapped[List["MessageAssets"]] = relationship("MessageAssets", back_populates="message")