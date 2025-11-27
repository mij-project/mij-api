from __future__ import annotations
from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .posts import Posts
    from .categories import Categories

class PostCategories(Base):
    """投稿カテゴリ"""
    __tablename__ = "post_categories"

    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True, index=True)
    category_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("categories.id", ondelete="RESTRICT"), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    post: Mapped["Posts"] = relationship("Posts", back_populates="post_categories")
    category: Mapped["Categories"] = relationship("Categories", back_populates="post_categories")
