# app/schemas/bulk_message.py
from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class BulkMessageRecipientsResponse(BaseModel):
    """一斉送信の送信先リストレスポンス"""
    chip_senders_count: int = Field(..., description="チップを送ってくれたユーザー数")
    single_purchasers_count: int = Field(..., description="単品販売購入ユーザー数")
    plan_subscribers: List[dict] = Field(..., description="プラン別加入者情報 [{'plan_id': UUID, 'plan_name': str, 'subscribers_count': int}]")

    class Config:
        from_attributes = True


class PresignedUrlRequest(BaseModel):
    """Presigned URL取得リクエスト"""
    asset_type: int = Field(..., ge=1, le=2, description="1=画像, 2=動画")
    content_type: str = Field(..., description="MIMEタイプ（例: image/jpeg, video/mp4）")
    file_extension: str = Field(..., max_length=10, description="ファイル拡張子（例: jpg, mp4）")


class PresignedUrlResponse(BaseModel):
    """Presigned URL取得レスポンス"""
    storage_key: str
    upload_url: str
    expires_in: int
    required_headers: dict


class BulkMessageSendRequest(BaseModel):
    """一斉送信リクエスト"""
    message_text: str = Field(..., min_length=1, max_length=1500, description="メッセージ本文")
    asset_storage_key: Optional[str] = Field(None, description="S3ストレージキー")
    asset_type: Optional[int] = Field(None, ge=1, le=2, description="1=画像, 2=動画")

    # 送信先選択
    send_to_chip_senders: bool = Field(False, description="チップを送ってくれたユーザーに送信")
    send_to_single_purchasers: bool = Field(False, description="単品販売購入ユーザーに送信")
    send_to_plan_subscribers: List[UUID] = Field(default_factory=list, description="送信対象プランIDリスト")

    # 予約送信
    scheduled_at: Optional[datetime] = Field(None, description="予約送信日時（UTC）")

    class Config:
        from_attributes = True


class BulkMessageSendResponse(BaseModel):
    """一斉送信レスポンス"""
    message: str
    sent_count: int = Field(..., description="送信数（即時送信の場合）または予約数（予約送信の場合）")
    scheduled: bool = Field(..., description="予約送信かどうか")
    scheduled_at: Optional[datetime] = Field(None, description="予約送信日時")

    class Config:
        from_attributes = True
