from __future__ import annotations
from typing import Optional, TYPE_CHECKING, List
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, BigInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users

class Companies(Base):
    """企業"""
    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_company_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    code: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True),    nullable=False, unique=True, server_default=func.gen_random_uuid())
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    parent: Mapped[Optional["Companies"]] = relationship(
        "Companies",
        remote_side=[id],
        back_populates="children",
        foreign_keys="Companies.parent_company_id"
    )
    children: Mapped[List["Companies"]] = relationship(
        "Companies",
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys="Companies.parent_company_id"
    )
    company_users: Mapped[List["CompanyUsers"]] = relationship("CompanyUsers", back_populates="company")


class CompanyUsers(Base):
    """企業ユーザー"""
    __tablename__ = "company_users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    company_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    company_fee_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    company: Mapped["Companies"] = relationship("Companies", back_populates="company_users")
    user: Mapped["Users"] = relationship("Users", back_populates="company_users")