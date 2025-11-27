from __future__ import annotations
from typing import Optional, List, TYPE_CHECKING
from uuid import UUID
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Text, BigInteger, SmallInteger, Integer, func, LargeBinary
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, NUMERIC
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .posts import Posts
    from .media_renditions import MediaRenditions
    from .media_rendition_jobs import MediaRenditionJobs

class MediaAssets(Base):
    """メディアアセット (投稿に紐づく画像や動画のリソース)"""
    __tablename__ = "media_assets"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_sec: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 3), nullable=True)
    orientation: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    reject_comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sample_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment='サンプル動画の種類: upload=アップロード, cut_out=本編から指定')
    sample_start_time: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 3), nullable=True, comment='本編から指定の場合の開始時間（秒）')
    sample_end_time: Mapped[Optional[Decimal]] = mapped_column(NUMERIC(10, 3), nullable=True, comment='本編から指定の場合の終了時間（秒）')
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    post: Mapped["Posts"] = relationship("Posts", back_populates="media_assets")
    renditions: Mapped[List["MediaRenditions"]] = relationship("MediaRenditions", back_populates="asset")
    rendition_jobs: Mapped[List["MediaRenditionJobs"]] = relationship("MediaRenditionJobs", back_populates="asset")
