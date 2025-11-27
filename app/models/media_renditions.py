from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Text, BigInteger, SmallInteger, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, NUMERIC
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .media_assets import MediaAssets

class MediaRenditions(Base):
    """メディアレンディション (メディアアセットのリソース)"""
    __tablename__ = "media_renditions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    asset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    asset: Mapped["MediaAssets"] = relationship("MediaAssets", back_populates="renditions")
