from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.constants.enums import ConversationType
from app.crud import conversations_crud
from app.schemas.conversation import (
    MessageCreate,
    MessageResponse,
    ConversationResponse
)
import os
router = APIRouter()

BASE_URL = os.getenv("CDN_BASE_URL")

# ========== 一般ユーザー用エンドポイント ==========

@router.get("/delusion", response_model=ConversationResponse)
def get_or_create_delusion_conversation(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    妄想メッセージ会話を取得または作成
    - 1ユーザーにつき1つの管理人トークルーム
    - 自動で作成される
    """
    conversation = conversations_crud.get_or_create_delusion_conversation(db, current_user.id)

    return ConversationResponse(
        id=conversation.id,
        type=conversation.type,
        is_active=conversation.is_active,
        last_message_id=conversation.last_message_id,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        unread_count=0
    )


@router.get("/delusion/messages", response_model=List[MessageResponse])
def get_delusion_messages(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    妄想メッセージの一覧を取得
    - 古い順にソート
    - 送信者情報（名前、アバター）を含む
    """
    # ユーザーの妄想メッセージ会話を取得
    conversation = conversations_crud.get_or_create_delusion_conversation(db, current_user.id)

    # メッセージ一覧を取得
    messages = conversations_crud.get_messages_by_conversation(
        db, conversation.id, skip, limit
    )

    # レスポンスを構築
    response = []
    for message, sender, profile, admin in messages:
        # 送信者情報の判定
        sender_username = None
        sender_avatar = None
        sender_profile_name = None

        if sender and profile:
            # ユーザーメッセージの場合
            sender_username = sender.profile_name
            sender_avatar = f"{BASE_URL}/{profile.avatar_url}" if profile.avatar_url else None
            sender_profile_name = sender.profile_name
        elif admin:
            # 管理者メッセージの場合
            sender_username = "運営"
            sender_avatar = None
            sender_profile_name = "運営"

        response.append(MessageResponse(
            id=message.id,
            conversation_id=message.conversation_id,
            sender_user_id=message.sender_user_id,
            sender_admin_id=message.sender_admin_id,
            type=message.type,
            body_text=message.body_text,
            created_at=message.created_at,
            updated_at=message.updated_at,
            sender_username=sender_username,
            sender_avatar=sender_avatar,
            sender_profile_name=sender_profile_name
        ))

    return response


@router.post("/delusion/messages", response_model=MessageResponse)
def send_delusion_message(
    message_data: MessageCreate,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    妄想メッセージを送信
    - テキストのみ対応
    """
    # ユーザーの妄想メッセージ会話を取得
    conversation = conversations_crud.get_or_create_delusion_conversation(db, current_user.id)

    # メッセージを作成
    message = conversations_crud.create_message(
        db=db,
        conversation_id=conversation.id,
        sender_user_id=current_user.id,
        body_text=message_data.body_text
    )

    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_user_id=message.sender_user_id,
        type=message.type,
        body_text=message.body_text,
        created_at=message.created_at,
        updated_at=message.updated_at,
        sender_username=current_user.username,
        sender_avatar=current_user.avatar_storage_key,
        sender_profile_name=current_user.profile_name
    )