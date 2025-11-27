from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime

# メッセージ作成リクエスト
class MessageCreate(BaseModel):
    body_text: str = Field(..., min_length=1, max_length=5000)

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
