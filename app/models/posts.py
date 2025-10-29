from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .post_categories import PostCategories
    from .media_assets import MediaAssets
    from .plans import PostPlans
    from .prices import Prices

class Posts(Base):
    __tablename__ = "posts"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    creator_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=False)
    visibility: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    post_type: Mapped[int] = mapped_column(SmallInteger, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    expiration_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    reject_comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    creator: Mapped["Users"] = relationship("Users", back_populates="posts")
    post_categories: Mapped[List["PostCategories"]] = relationship("PostCategories", back_populates="post")
    media_assets: Mapped[List["MediaAssets"]] = relationship("MediaAssets", back_populates="post")
    post_plans: Mapped[List["PostPlans"]] = relationship("PostPlans", back_populates="post")
    prices: Mapped[List["Prices"]] = relationship("Prices", back_populates="post")
