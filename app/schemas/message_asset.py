# app/schemas/message_asset.py
from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime


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


class MessageAssetCreate(BaseModel):
    """メッセージアセット作成リクエスト（メッセージ送信時）"""
    asset_storage_key: Optional[str] = Field(None, description="S3ストレージキー")
    asset_type: Optional[int] = Field(None, ge=1, le=2, description="1=画像, 2=動画")


class MessageAssetResponse(BaseModel):
    """メッセージアセットレスポンス"""
    id: UUID
    status: int  # 0=審査待ち, 1=承認済み, 2=拒否
    asset_type: int  # 1=画像, 2=動画
    storage_key: str
    cdn_url: Optional[str] = None  # 承認済みの場合のみCloudFront URL
    reject_comments: Optional[str] = None  # 拒否時のコメント
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageAssetApproveRequest(BaseModel):
    """メッセージアセット承認リクエスト（管理画面用）"""
    pass  # リクエストボディ不要


class MessageAssetRejectRequest(BaseModel):
    """メッセージアセット拒否リクエスト（管理画面用）"""
    reject_comments: str = Field(..., min_length=1, max_length=500, description="拒否理由")


class MessageAssetResubmitRequest(BaseModel):
    """メッセージアセット再申請リクエスト（ユーザー用）"""
    message_text: Optional[str] = Field(None, max_length=1000, description="メッセージ本文（オプション）")
    asset_storage_key: str = Field(..., description="新しいアセットのS3ストレージキー")
    asset_type: int = Field(..., ge=1, le=2, description="1=画像, 2=動画")



class UserMessageAssetResponse(BaseModel):
    """ユーザーのメッセージアセットレスポンス（一覧用）"""
    id: UUID
    message_id: UUID
    conversation_id: UUID
    asset_type: int  # 1=画像, 2=動画
    storage_key: str
    cdn_url: Optional[str] = None
    reject_comments: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # メッセージ情報
    message_text: Optional[str] = None

    # 相手の情報
    partner_user_id: Optional[UUID] = None
    partner_username: Optional[str] = None
    partner_profile_name: Optional[str] = None
    partner_avatar: Optional[str] = None

    class Config:
        from_attributes = True


class UserMessageAssetDetailResponse(BaseModel):
    """ユーザーのメッセージアセット詳細レスポンス"""
    id: UUID
    message_id: UUID
    conversation_id: UUID
    status: int  # 0=審査待ち, 1=承認済み, 2=拒否
    asset_type: int  # 1=画像, 2=動画
    storage_key: str
    cdn_url: Optional[str] = None
    reject_comments: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # メッセージ全文
    message_text: Optional[str] = None
    message_created_at: Optional[datetime] = None

    # 相手の情報
    partner_user_id: Optional[UUID] = None
    partner_username: Optional[str] = None
    partner_profile_name: Optional[str] = None
    partner_avatar: Optional[str] = None

    class Config:
        from_attributes = True


class UserMessageAssetsListResponse(BaseModel):
    """ユーザーのメッセージアセット一覧レスポンス"""
    pending_message_assets: List[UserMessageAssetResponse]
    reject_message_assets: List[UserMessageAssetResponse]

    class Config:
        from_attributes = True


class AdminMessageAssetListResponse(BaseModel):
    """管理者用メッセージアセット一覧レスポンス"""
    id: UUID
    message_id: UUID
    conversation_id: UUID
    status: int  # 0=審査待ち, 1=承認済み, 2=拒否
    asset_type: int  # 1=画像, 2=動画
    storage_key: str
    cdn_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # メッセージ情報
    message_text: Optional[str] = None

    # 送信者情報
    sender_user_id: Optional[UUID] = None
    sender_username: Optional[str] = None
    sender_profile_name: Optional[str] = None
    sender_avatar: Optional[str] = None

    # 受信者情報
    recipient_user_id: Optional[UUID] = None
    recipient_username: Optional[str] = None
    recipient_profile_name: Optional[str] = None
    recipient_avatar: Optional[str] = None

    class Config:
        from_attributes = True


class AdminMessageAssetDetailResponse(BaseModel):
    """管理者用メッセージアセット詳細レスポンス"""
    id: UUID
    message_id: UUID
    conversation_id: UUID
    status: int  # 0=審査待ち, 1=承認済み, 2=拒否
    asset_type: int  # 1=画像, 2=動画
    storage_key: str
    cdn_url: Optional[str] = None
    reject_comments: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # メッセージ全文
    message_text: Optional[str] = None
    message_created_at: Optional[datetime] = None

    # 送信者情報
    sender_user_id: Optional[UUID] = None
    sender_username: Optional[str] = None
    sender_profile_name: Optional[str] = None
    sender_avatar: Optional[str] = None

    # 受信者情報
    recipient_user_id: Optional[UUID] = None
    recipient_username: Optional[str] = None
    recipient_profile_name: Optional[str] = None
    recipient_avatar: Optional[str] = None

    class Config:
        from_attributes = True
