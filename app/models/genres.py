from __future__ import annotations
from typing import List, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, Boolean, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, CITEXT
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .categories import Categories

class Genres(Base):
    """ジャンル(カテゴリの親)"""
    __tablename__ = "genres"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    slug: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    categories: Mapped[List["Categories"]] = relationship("Categories", back_populates="genre")

if TYPE_CHECKING:
    from .categories import Categories
