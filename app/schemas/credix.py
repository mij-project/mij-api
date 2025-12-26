"""
CREDIX決済スキーマ
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from enum import Enum


class PurchaseType(str, Enum):
    """購入タイプ"""
    SINGLE = "single"
    SUBSCRIPTION = "subscription"


class CredixSessionRequest(BaseModel):
    """CREDIXセッション発行リクエスト"""
    order_id: str = Field(..., description="投稿ID")
    purchase_type: PurchaseType = Field(..., description="購入タイプ（single/subscription）")
    plan_id: Optional[str] = Field(None, description="プランID（サブスクリプションの場合）")
    price_id: Optional[str] = Field(None, description="価格ID（単発購入の場合）")
    is_time_sale: bool = Field(False, description="時間販売の場合はTrue、それ以外はFalse")


class CredixSessionResponse(BaseModel):
    """CREDIXセッション発行レスポンス"""
    session_id: str = Field(..., description="セッションID")
    payment_url: str = Field(..., description="決済画面URL")
    transaction_id: str = Field(..., description="トランザクションID（UUID）")


class CredixSessionResponse(BaseModel):
    """CREDIXセッション発行レスポンス"""
    session_id: str = Field(..., description="セッションID")
    payment_url: str = Field(..., description="決済画面URL")
    transaction_id: str = Field(..., description="トランザクションID（UUID）")

class CredixWebhookRequest(BaseModel):
    """CREDIX Webhook受信リクエスト"""
    result: str = Field(..., description="決済結果（OK/NG）")
    clientip: str = Field(..., description="IPコード")
    money: int = Field(..., description="決済金額")
    telno: str = Field(..., description="電話番号")
    email: EmailStr = Field(..., description="メールアドレス")
    sendid: str = Field(..., description="カードID")
    sendpoint: Optional[str] = Field(None, description="フリーパラメータ")


class CredixPaymentResultResponse(BaseModel):
    """決済結果確認レスポンス"""
    status: str = Field(..., description="決済ステータス（pending/completed/failed）")
    result: str = Field(..., description="決済結果（success/failure/pending）")
    transaction_id: str = Field(..., description="トランザクションID")
    payment_id: Optional[str] = Field(None, description="決済ID")
    subscription_id: Optional[str] = Field(None, description="サブスクリプションID")


class ChipPaymentRequest(BaseModel):
    """投げ銭決済リクエスト"""
    recipient_user_id: str = Field(..., description="受取人ユーザーID")
    amount: int = Field(..., description="投げ銭金額", ge=500, le=10000)
    message: Optional[str] = Field(None, description="メッセージ")
