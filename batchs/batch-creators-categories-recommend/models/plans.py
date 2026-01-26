from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, BigInteger, Integer, func, Boolean
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from common.db_session import Base


class Plans(Base):
    __tablename__ = "plans"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    creator_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    display_order: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    open_dm_flg: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    welcome_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

class PostPlans(Base):
    __tablename__ = "post_plans"

    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

