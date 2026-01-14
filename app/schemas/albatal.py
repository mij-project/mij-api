from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional
from enum import Enum

class PurchaseType(str, Enum):
    """購入タイプ"""
    SINGLE = "single"
    SUBSCRIPTION = "subscription"
    CHIPS = "chips"

class AlbatalSessionRequest(BaseModel):
    order_id: str = Field(..., description="投稿ID")
    purchase_type: PurchaseType = Field(..., description="購入タイプ（single/subscription）")
    plan_id: Optional[str] = Field(None, description="プランID（サブスクリプションの場合）")
    price_id: Optional[str] = Field(None, description="価格ID（単発購入の場合）")
    is_time_sale: bool = Field(False, description="時間販売の場合はTrue、それ以外はFalse")
    provider_email: Optional[str] = Field(None, description="プロバイダーのメールアドレス")
    return_url: Optional[str] = Field(None, description="定期決済完了後のリダイレクトURL")

class AlbatalSessionResponse(BaseModel):
    success_url: str = Field(..., description="決済成功後のリダイレクトURL")
    failure_url: str = Field(..., description="決済失敗後のリダイレクトURL")
    transaction_id: UUID = Field(..., description="トランザクションID")
    payment_url: str = Field(..., description="Albatal WPF決済画面URL")


class AlbatalWebhookPaymentNotification(BaseModel):
    """Albatal決済完了ウェブフック通知"""
    wpf_transaction_id: Optional[str] = Field(None, description="WPF トランザクションID")
    wpf_status: Optional[str] = Field(None, description="WPF トランザクション状態")
    wpf_unique_id: Optional[str] = Field(None, description="WPF ユニークID")
    payment_transaction_unique_id: Optional[str] = Field(None, description="決済トランザクションユニークID")
    payment_transaction_amount: Optional[str] = Field(None, description="決済金額")
    consumer_id: Optional[str] = Field(None, description="コンシューマーID")
    notification_type: Optional[str] = Field(None, description="通知タイプ")
    signature: Optional[str] = Field(None, description="署名（検証用）")
    clientip: Optional[str] = Field(None, description="クライアントIP")


class AlbatalWebhookRecurringNotification(BaseModel):
    """Albatal定期決済ウェブフック通知"""
    transaction_id: Optional[str] = Field(None, description="トランザクションID")
    unique_id: Optional[str] = Field(None, description="ユニークID")
    merchant_transaction_id: Optional[str] = Field(None, description="マーチャント トランザクションID")
    status: Optional[str] = Field(None, description="トランザクション状態")
    amount: Optional[str] = Field(None, description="金額")
    signature: Optional[str] = Field(None, description="署名（検証用）")