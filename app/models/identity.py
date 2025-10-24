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

class IdentityVerifications(Base):
    """身元確認"""
    __tablename__ = "identity_verifications"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    approved_by: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("admins.id"), nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    checked_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["Users"] = relationship("Users")
    approver: Mapped[Optional["Admins"]] = relationship("Admins", foreign_keys=[approved_by])
    documents: Mapped[list["IdentityDocuments"]] = relationship("IdentityDocuments", back_populates="verification")

class IdentityDocuments(Base):
    """身元確認書類"""
    __tablename__ = "identity_documents"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    verification_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("identity_verifications.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    verification: Mapped["IdentityVerifications"] = relationship("IdentityVerifications", back_populates="documents")
