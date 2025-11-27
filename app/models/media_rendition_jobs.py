# app/models/media_rendition_jobs.py
from __future__ import annotations
from typing import Optional, Dict, Any, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base

if TYPE_CHECKING:
    from .media_renditions import MediaRenditions
    from .media_assets import MediaAssets
    
class MediaRenditionJobs(Base):
    """メディアレンディションジョブ(media convert後のリソース)"""
    __tablename__ = "media_rendition_jobs"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    asset_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="CASCADE"), index=True, nullable=False)

    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)     # PREVIEW_MP4 / HLS_ABR4
    backend: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)

    # 入出力指定
    input_key: Mapped[str] = mapped_column(Text, nullable=False)            # 例 "post-media/main/<post>/<uuid>.mp4"
    output_prefix: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # HLS 例 "hls/<post>/<asset>/"
    output_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # プレビュー 例 "preview/<post>/<asset>/preview.mp4"

    # 実行情報
    job_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)      # MediaConvert JobId

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    asset: Mapped["MediaAssets"] = relationship("MediaAssets", back_populates="rendition_jobs")