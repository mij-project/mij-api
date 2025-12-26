from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, SmallInteger, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import Base

if TYPE_CHECKING:
    from .plans import Plans
    from .posts import Posts
    from .prices import Prices

class TimeSale(Base):
    __tablename__ = "time_sale"
    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    post_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("posts.id", ondelete="CASCADE"), nullable=True)
    plan_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), nullable=True)
    price_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("prices.id", ondelete="CASCADE"), nullable=True)
    start_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    sale_percentage: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    sale_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    max_purchase_count: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    plan: Mapped["Plans"] = relationship("Plans")
    post: Mapped["Posts"] = relationship("Posts")
    price: Mapped["Prices"] = relationship("Prices")