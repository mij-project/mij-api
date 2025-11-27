from __future__ import annotations
from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, PrimaryKeyConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .gender import Gender

class CreatorType(Base):
    """クリエイタータイプ (ユーザーと性別の多対多)"""
    __tablename__ = "creator_type"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    gender_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("gender.id", ondelete="RESTRICT"), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "gender_id", name="pk_creator_type"),
    )

    user: Mapped["Users"] = relationship("Users", back_populates="creator_type")
    gender: Mapped["Gender"] = relationship("Gender", back_populates="creator_type")
