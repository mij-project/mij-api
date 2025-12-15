from __future__ import annotations
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import Text, SmallInteger, func, PrimaryKeyConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from common.db_session import Base

class Events(Base):
    __tablename__ = "events"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    start_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class UserEvents(Base):
    __tablename__ = "user_events"

    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    __table_args__ = (
        PrimaryKeyConstraint("user_id", "event_id", name="pk_user_events"),
    )