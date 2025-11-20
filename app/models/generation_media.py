from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .posts import Posts
    from .user import Users

class GenerationMedia(Base):
    """生成メディア"""
    __tablename__ = "generation_media"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1) # 1: プロフィール画像, 2: 投稿画像
    # null許容
    user_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)

    post_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    user: Mapped[Optional["Users"]] = relationship("Users", back_populates="generation_media", foreign_keys=[user_id])
    post: Mapped[Optional["Posts"]] = relationship("Posts", back_populates="generation_media", foreign_keys=[post_id])