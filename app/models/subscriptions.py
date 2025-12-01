from __future__ import annotations
from typing import Optional, List, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, BigInteger, func, String, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .user import Users
    from .plans import Plans
    from .prices import Prices
    from .providers import Providers
    from .payments import Payments
    from .payment_transactions import PaymentTransactions

class Subscriptions(Base):
    """コンテンツアクセス権限管理（プラン購読＋単品購入）"""
    __tablename__ = "subscriptions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    # アクセス権限の種別
    access_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, index=True, comment="1=plan_subscription（プラン購読）, 2=one_time_purchase（単品購入）")

    # ユーザー情報
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True, comment="購入者（この人に視聴権限を付与）")
    creator_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True, comment="クリエイター（販売者）")

    # プランまたは商品の識別（どちらか一方のみNULL以外）
    order_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="plan_id（サブスク）またはprice_id（単品販売）")
    order_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=plan_id, 2=price_id")

    # 視聴権限期間管理
    access_start: Mapped[datetime] = mapped_column(nullable=False, index=True, comment="視聴可能開始日（プラン: 課金開始日、単品: 購入日）")
    access_end: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True, comment="視聴可能終了日（プラン: 課金期間終了日、単品: NULL=永久アクセス）")

    # ステータス管理
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, index=True, comment="1=active（視聴可）, 2=canceled（期末まで視聴可）, 3=expired（期限切れ）, 4=refunded（返金済み）")

    # プラン購読専用フィールド
    cancel_at_period_end: Mapped[bool] = mapped_column(nullable=False, default=False, comment="プラン購読: 期末でキャンセル予定（access_endまで視聴可能）")
    canceled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="プラン購読: キャンセル申請日時")

    # プラン購読専用: 次回課金予定
    next_billing_date: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True, comment="プラン購読: 次回課金予定日（バッチでチェック）")

    # プラン購読専用: 課金失敗管理
    failed_payment_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="プラン購読: 連続課金失敗回数")
    last_payment_failed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="プラン購読: 最終課金失敗日時")

    # 関連する決済情報
    provider_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("providers.id"), nullable=True, comment="決済プロバイダーID")
    payment_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True, comment="初回決済ID（または最新の決済ID）")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["Users"] = relationship("Users", foreign_keys=[user_id], back_populates="subscriptions")
    creator: Mapped["Users"] = relationship("Users", foreign_keys=[creator_id], back_populates="creator_subscriptions")
    provider: Mapped[Optional["Providers"]] = relationship("Providers", foreign_keys=[provider_id], back_populates="subscriptions")
    payment: Mapped[Optional["Payments"]] = relationship("Payments", back_populates="subscription")
