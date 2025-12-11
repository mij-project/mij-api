from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, BigInteger, func, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .payment_transactions import PaymentTransactions
    from .providers import Providers
    from .user import Users
    from .subscriptions import Subscriptions

class Payments(Base):
    """決済履歴"""
    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    # トランザクション参照（0円の場合はNULL）
    transaction_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payment_transactions.id"), nullable=True, index=True, comment="元となったCredixトランザクション")

    # 決済種別
    payment_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="2=subscription(plan_id), 1=one_time_purchase(price_id)")

    # order_id: plan_id または price_id を格納
    order_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="plan_id（サブスク）またはprice_id（単品販売）")
    order_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=plan_id, 2=price_id")

    # 決済プロバイダー情報（0円の場合はNULL）
    provider_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("providers.id"), nullable=True)
    provider_payment_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Credix決済ID（session_id）")

    # 支払った人と金額を明確に管理
    buyer_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True, comment="支払った人（購入者）")
    seller_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True, comment="販売者（クリエイター）")

    # 金額情報の詳細管理（円単位）
    payment_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="支払総額（buyer_user_idが実際に支払った金額 = item_price + purchase_fee）")
    payment_price: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="支払い金額（price or plan.price）")

    # ステータス管理
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, index=True, comment="1=pending, 2=succeeded, 3=failed, 4=refunded, 5=partially_refunded")

    # エラー情報
    failure_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 決済完了日時
    paid_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True, comment="実際の決済完了日時")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # その時のプラットフォーム手数料
    platform_fee: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="その時のプラットフォーム手数料")

    # Relationships
    transaction: Mapped[Optional["PaymentTransactions"]] = relationship("PaymentTransactions", foreign_keys=[transaction_id], back_populates="payment")
    provider: Mapped[Optional["Providers"]] = relationship("Providers", back_populates="payments")
    buyer: Mapped["Users"] = relationship("Users", foreign_keys=[buyer_user_id], back_populates="purchases")
    seller: Mapped["Users"] = relationship("Users", foreign_keys=[seller_user_id], back_populates="sales")
    subscription: Mapped[Optional["Subscriptions"]] = relationship("Subscriptions", back_populates="payment")
