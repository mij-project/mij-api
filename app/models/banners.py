from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, BigInteger, Integer, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm import relationship

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users

class Banners(Base):
    """バナー"""
    __tablename__ = "banners"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    image_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    alt_text: Mapped[str] = mapped_column(Text, nullable=False)
    cta_label: Mapped[str] = mapped_column(Text, nullable=False)
    creator_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    external_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    start_at: Mapped[datetime] = mapped_column(nullable=True)
    end_at: Mapped[datetime] = mapped_column(nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_source: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    creator: Mapped["Users"] = relationship("Users", back_populates="banners")