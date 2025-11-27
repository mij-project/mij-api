from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, Boolean, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, CITEXT
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .genres import Genres
    from .creators import Creators
    from .post_categories import PostCategories

class Categories(Base):
    """カテゴリ(ジャンルの子)"""
    __tablename__ = "categories"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    genre_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("genres.id", ondelete="RESTRICT"), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    genre: Mapped["Genres"] = relationship("Genres", back_populates="categories")
    post_categories: Mapped[List["PostCategories"]] = relationship("PostCategories", back_populates="category")
