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
    from .subscriptions import Subscriptions
    from .providers import Providers
    from .user import Users

class Payments(Base):
    """決済履歴"""
    __tablename__ = "payments"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    # トランザクション参照
    transaction_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payment_transactions.id"), nullable=False, index=True, comment="元となったCredixトランザクション")

    # 決済種別
    payment_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=subscription(plan_id), 2=one_time_purchase(price_id)")

    # 関連オブジェクト（どちらか一方のみ設定）
    subscription_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True, index=True, comment="サブスクリプションIDの場合")

    # order_id: plan_id または price_id を格納
    order_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="plan_id（サブスク）またはprice_id（単品販売）")
    order_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=plan_id, 2=price_id")

    # 決済プロバイダー情報
    provider_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)
    provider_payment_id: Mapped[str] = mapped_column(Text, nullable=False, comment="Credix決済ID（session_id）")

    # 支払った人と金額を明確に管理
    buyer_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True, comment="支払った人（購入者）")
    seller_user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True, comment="販売者（クリエイター）")

    # 金額情報の詳細管理（円単位）
    item_price: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="商品価格（円）")
    purchase_fee: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="購入手数料10%（購入者が追加で支払う）")
    payment_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="支払総額（buyer_user_idが実際に支払った金額 = item_price + purchase_fee）")

    # クリエイター収益計算
    platform_fee_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="プラットフォーム手数料率（creators.platform_fee_percentのコピー）")
    platform_fee: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="プラットフォーム手数料（item_price × platform_fee_percent / 100）")
    creator_earnings: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="クリエイター収益（item_price - platform_fee）")

    # ステータス管理
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, index=True, comment="1=pending, 2=succeeded, 3=failed, 4=refunded, 5=partially_refunded")

    # 返金情報
    refunded_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="返金済み金額")
    refunded_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # エラー情報
    failure_code: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    failure_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 決済完了日時
    paid_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True,
                                                         comment="実際の決済完了日時")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    transaction: Mapped["PaymentTransactions"] = relationship("PaymentTransactions", foreign_keys=[transaction_id], back_populates="payment")
    subscription: Mapped[Optional["Subscriptions"]] = relationship("Subscriptions", foreign_keys=[subscription_id], back_populates="payments")
    subscription_initial: Mapped[Optional["Subscriptions"]] = relationship("Subscriptions", foreign_keys="Subscriptions.payment_id", back_populates="initial_payment")
    provider: Mapped["Providers"] = relationship("Providers", back_populates="payments")
    buyer: Mapped["Users"] = relationship("Users", foreign_keys=[buyer_user_id], back_populates="purchases")
    seller: Mapped["Users"] = relationship("Users", foreign_keys=[seller_user_id], back_populates="sales")
