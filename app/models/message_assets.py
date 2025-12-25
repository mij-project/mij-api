from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, Integer, func, Boolean
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .conversation_messages import ConversationMessages

class MessageAssets(Base):
    """メッセージアセット"""
    __tablename__ = "message_assets"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    message_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("conversation_messages.id"), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    asset_type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    reject_comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    message: Mapped["ConversationMessages"] = relationship("ConversationMessages")