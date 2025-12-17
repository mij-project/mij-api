from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, Boolean, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from common.db_session import Base

class Users(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    profile_name: Mapped[Optional[str]] = mapped_column(CITEXT, unique=True, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(CITEXT, unique=True, nullable=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    is_identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    phone_verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    identity_verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    offical_flg: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)