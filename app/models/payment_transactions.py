from __future__ import annotations
from typing import Optional, TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, func, String, Text, BigInteger, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .payments import Payments
    from .subscriptions import Subscriptions
    from .user import Users
    from .providers import Providers

class PaymentTransactions(Base):
    """Credix決済トランザクション管理"""
    __tablename__ = "payment_transactions"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())

    # トランザクション種別
    transaction_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=initial_payment, 2=recurring_payment, 3=one_time_purchase")

    # 関連情報
    payment_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True, comment="決済完了後に紐付け")
    subscription_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True, comment="サブスクリプションID（継続課金の場合）")
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, comment="購入者（buyer）")
    creator_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, comment="販売者（seller/creator）")

    # Credix固有情報
    provider_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), ForeignKey("providers.id"), nullable=False)

    # Credixセッション情報
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True, comment="Credixセッション識別子（sid）")
    session_expires_at: Mapped[datetime] = mapped_column(nullable=False, comment="セッション有効期限（発行から60分）")

    # order_id: plan_id または price_id
    order_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True, comment="plan_id（サブスク）またはprice_id（単品販売）")
    order_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, comment="1=plan_id, 2=price_id")

    # 決済金額
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="商品価格（円）")
    purchase_fee: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="購入手数料（10%）")
    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="支払総額（amount + purchase_fee）")

    # Credix WebhookパラメータEsro（CGIコールで受信）
    credix_result: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, comment="Webhook result: OK/NG")
    credix_clientip: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, comment="Credix IPコード")
    credix_telno: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, comment="Webhook telno")
    credix_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Webhook email")
    credix_sendid: Mapped[Optional[str]] = mapped_column(String(25), nullable=True, index=True, comment="カードID（顧客識別用、リピーター決済キー）")
    credix_sendpoint: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="フリーパラメータ（自由利用）")

    # ステータス管理
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, index=True, comment="1=session_issued, 2=payment_screen_opened, 3=completed, 4=failed, 5=expired")

    # 日時管理
    session_issued_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), comment="セッション発行日時")
    payment_screen_opened_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="決済画面表示日時")
    webhook_received_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="Webhook受信日時")
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, comment="決済完了日時")

    # Webhookの生データ保存
    webhook_raw_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True, comment="Webhookの生データ（JSON）")

    # エラー情報
    error_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # リトライ管理
    webhook_retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="Webhookリトライ回数")
    last_webhook_retry_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now(), onupdate=func.now())

    # Relationships
    payment: Mapped[Optional["Payments"]] = relationship("Payments", back_populates="transaction", foreign_keys="Payments.transaction_id")
    subscription: Mapped[Optional["Subscriptions"]] = relationship("Subscriptions", back_populates="payment_transactions")
    buyer: Mapped["Users"] = relationship("Users", foreign_keys=[user_id], back_populates="buyer_transactions")
    seller: Mapped["Users"] = relationship("Users", foreign_keys=[creator_id], back_populates="seller_transactions")
    provider: Mapped["Providers"] = relationship("Providers", back_populates="payment_transactions")
