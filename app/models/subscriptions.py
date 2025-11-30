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
    plan_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("plans.id"), nullable=True, index=True, comment="プラン購読の場合のプランID")

    # 単品購入の場合の商品識別
    content_type: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True, comment="1=post（投稿）, 2=album（アルバム）, 3=video（動画）など")
    content_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True, comment="単品購入の場合のコンテンツID（post_id等）")
    price_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("prices.id"), nullable=True, index=True, comment="単品購入の場合の価格ID")

    # Credix情報（継続課金の場合のみ使用）
    provider_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("providers.id"), nullable=True, comment="プラン購読の場合のみ必須")
    credix_sendid: Mapped[Optional[str]] = mapped_column(String(25), nullable=True, index=True, comment="CredixカードID（プラン購読の継続課金用）")

    # 視聴権限期間管理
    access_start: Mapped[datetime] = mapped_column(nullable=False, index=True, comment="視聴可能開始日（プラン: 課金開始日、単品: 購入日）")
    access_end: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True, comment="視聴可能終了日（プラン: 課金期間終了日、単品: NULL=永久アクセス）")

    # ステータス管理
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, index=True, comment="1=active（視聴可）, 2=canceled（期末まで視聴可）, 3=expired（期限切れ）, 4=refunded（返金済み）")

    # プラン購読専用フィールド
    cancel_at_period_end: Mapped[bool] = mapped_column(nullable=False, default=False, comment="プラン購読: 期末でキャンセル予定（access_endまで視聴可能）")
    canceled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="プラン購読: キャンセル申請日時")

    # 料金情報（購入時点の価格を保存）
    price: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="料金（円）※プラン: 月額、単品: 商品価格")
    purchase_fee: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="購入手数料（10%）")

    # プラン購読専用: 次回課金予定
    next_billing_date: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True, comment="プラン購読: 次回課金予定日（バッチでチェック）")

    # プラン購読専用: 課金失敗管理
    failed_payment_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="プラン購読: 連続課金失敗回数")
    last_payment_failed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="プラン購読: 最終課金失敗日時")

    # 関連する決済情報
    payment_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True, comment="初回決済ID（または最新の決済ID）")

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["Users"] = relationship("Users", foreign_keys=[user_id], back_populates="subscriptions")
    creator: Mapped["Users"] = relationship("Users", foreign_keys=[creator_id], back_populates="creator_subscriptions")
    plan: Mapped[Optional["Plans"]] = relationship("Plans", back_populates="subscriptions")
    price_model: Mapped[Optional["Prices"]] = relationship("Prices", back_populates="subscriptions")
    provider: Mapped[Optional["Providers"]] = relationship("Providers", back_populates="subscriptions")
    initial_payment: Mapped[Optional["Payments"]] = relationship("Payments", foreign_keys=[payment_id], back_populates="subscription_initial")
    payment_transactions: Mapped[List["PaymentTransactions"]] = relationship("PaymentTransactions", back_populates="subscription")
    payments: Mapped[List["Payments"]] = relationship("Payments", foreign_keys="Payments.subscription_id", back_populates="subscription")

    __table_args__ = (
        # プラン購読の場合はplan_idが必須
        CheckConstraint(
            "(access_type = 1 AND plan_id IS NOT NULL) OR access_type != 1",
            name="check_plan_subscription_has_plan_id"
        ),

        # 単品購入の場合はcontent_idとcontent_typeが必須
        CheckConstraint(
            "(access_type = 2 AND content_id IS NOT NULL AND content_type IS NOT NULL) OR access_type != 2",
            name="check_one_time_purchase_has_content"
        ),

        # プラン購読の場合はprovider_idが必須（継続課金のため）
        CheckConstraint(
            "(access_type = 1 AND provider_id IS NOT NULL) OR access_type != 1",
            name="check_plan_subscription_has_provider"
        ),

        # パフォーマンス最適化用の複合インデックス
        Index('ix_subscriptions_access_check', 'user_id', 'status', 'access_start', 'access_end'),
        Index('ix_subscriptions_content_access', 'content_id', 'content_type', 'status'),
        Index('ix_subscriptions_plan_access', 'plan_id', 'status'),

        # 同じユーザーが同じコンテンツを重複購入しないようにする（単品購入）- 条件付きユニーク制約
        Index('uq_user_content_access', 'user_id', 'content_id', 'content_type', 'access_type',
              unique=True,
              postgresql_where="access_type = 2 AND status != 4"),  # refunded以外

        # 同じユーザーが同じプランを重複購読しないようにする - 条件付きユニーク制約
        Index('uq_user_plan_subscription', 'user_id', 'plan_id', 'access_type',
              unique=True,
              postgresql_where="access_type = 1 AND status IN (1, 2)"),  # active or canceled
    )
