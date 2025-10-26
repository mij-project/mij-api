from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .admins import Admins

class ProfileImageSubmissions(Base):
    """プロフィール画像申請

    ユーザーが申請したアバター画像またはカバー画像の審査状態を管理する。
    管理者による承認後、profilesテーブルのavatar_url/cover_urlが更新される。
    """
    __tablename__ = "profile_image_submissions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    image_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=avatar, 2=cover")
    storage_key: Mapped[str] = mapped_column(Text, nullable=False, comment="S3ストレージキー")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1=pending, 2=approved, 3=rejected")
    approved_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("admins.id"), nullable=True)
    checked_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="審査日時")
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="却下理由")
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # リレーション
    user: Mapped["Users"] = relationship("Users")
    approver: Mapped[Optional["Admins"]] = relationship("Admins", foreign_keys=[approved_by])
