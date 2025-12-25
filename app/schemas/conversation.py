from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime

# メッセージ作成リクエスト
class MessageCreate(BaseModel):
    body_text: Optional[str] = Field(None, max_length=5000)  # テキストのみ、またはアセットのみも許可
    asset_storage_key: Optional[str] = None  # アセットのS3キー（オプション）
    asset_type: Optional[int] = Field(None, ge=1, le=2)  # 1=画像, 2=動画（オプション）

# メッセージアセット情報（MessageResponse内で使用）
class MessageAssetInfo(BaseModel):
    id: UUID
    status: int  # 0=審査待ち, 1=承認済み, 2=拒否
    asset_type: int  # 1=画像, 2=動画
    cdn_url: Optional[str] = None  # 承認済みの場合のみ
    storage_key: str

    class Config:
        from_attributes = True

# メッセージレスポンス
class MessageResponse(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_user_id: Optional[UUID] = None
    sender_admin_id: Optional[UUID] = None
    type: int
    body_text: Optional[str]
    created_at: datetime
    updated_at: datetime

    # 送信者情報
    sender_username: Optional[str] = None
    sender_avatar: Optional[str] = None
    sender_profile_name: Optional[str] = None

    # アセット情報（オプション）
    asset: Optional[MessageAssetInfo] = None

    class Config:
        from_attributes = True

# 会話レスポンス
class ConversationResponse(BaseModel):
    id: UUID
    type: int
    is_active: bool
    last_message_id: Optional[UUID]
    last_message_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    # 最後のメッセージ内容（プレビュー用）
    last_message_text: Optional[str] = None

    # 未読カウント（管理人用）
    unread_count: Optional[int] = 0

    class Config:
        from_attributes = True

# 会話一覧レスポンス（管理人用）
class ConversationListResponse(BaseModel):
    id: UUID
    user_id: UUID
    user_username: Optional[str]
    user_profile_name: Optional[str]
    user_avatar: Optional[str]
    last_message_text: Optional[str]
    last_message_at: Optional[datetime]
    unread_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True

# 管理人側の未読カウント
class UnreadCountResponse(BaseModel):
    unread_count: int

# 既読更新リクエスト
class MarkAsReadRequest(BaseModel):
    message_id: UUID

# 会話メッセージレスポンス（相手のプロフィール情報を含む）
class ConversationMessagesResponse(BaseModel):
    messages: List[MessageResponse]
    partner_user_id: Optional[UUID] = None
    partner_username: Optional[str] = None
    partner_profile_name: Optional[str] = None
    partner_avatar: Optional[str] = None
    can_send_message: bool = False
    current_user_is_creator: bool = False
    partner_user_is_creator: bool = False

    class Config:
        from_attributes = True
