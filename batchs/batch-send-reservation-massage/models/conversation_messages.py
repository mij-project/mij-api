from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.db_session import Base


class ConversationMessages(Base):
    """会話ルームメッセージ"""
    __tablename__ = "conversation_messages"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    conversation_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    sender_user_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    sender_admin_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=True, default=1)
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    group_by: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    body_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_message_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    moderation: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
