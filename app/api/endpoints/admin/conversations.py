from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.models.admins import Admins
from app.constants.enums import ConversationType
from app.crud import conversations_crud
from app.schemas.conversation import (
    MessageCreate,
    MessageResponse,
    ConversationListResponse,
    MarkAsReadRequest
)
import os
BASE_URL = os.getenv("CDN_BASE_URL")

router = APIRouter()


# ========== 管理人用エンドポイント ==========

@router.get("/conversations/delusion/list", response_model=List[ConversationListResponse])
def get_all_delusion_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    管理人用: すべての妄想メッセージ会話一覧を取得
    - 最後のメッセージ時刻でソート
    - 未読カウントを含む
    """
    conversations = conversations_crud.get_all_delusion_conversations_for_admin(
        db, skip, limit
    )

    return [ConversationListResponse(**conv) for conv in conversations]


@router.get("/conversations/delusion/{conversation_id}/messages", response_model=List[MessageResponse])
def get_conversation_messages_admin(
    conversation_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    管理人用: 特定会話のメッセージ一覧を取得
    """
    conversation = conversations_crud.get_conversation_by_id(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation.type != ConversationType.DELUSION:
        raise HTTPException(status_code=403, detail="Not a delusion conversation")

    messages = conversations_crud.get_messages_by_conversation(
        db, conversation_id, skip, limit
    )

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


@router.post("/conversations/delusion/{conversation_id}/messages", response_model=MessageResponse)
def send_message_as_admin(
    conversation_id: UUID,
    message_data: MessageCreate,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    管理人用: メッセージを送信
    """
    conversation = conversations_crud.get_conversation_by_id(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation.type != ConversationType.DELUSION:
        raise HTTPException(status_code=403, detail="Not a delusion conversation")

    message = conversations_crud.create_message(
        db=db,
        conversation_id=conversation_id,
        sender_admin_id=current_admin.id,
        body_text=message_data.body_text
    )

    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_user_id=message.sender_user_id,
        sender_admin_id=message.sender_admin_id,
        type=message.type,
        body_text=message.body_text,
        created_at=message.created_at,
        updated_at=message.updated_at,
        sender_username="運営",
        sender_avatar=None,
        sender_profile_name="運営"
    )


@router.post("/conversations/delusion/{conversation_id}/mark-read")
def mark_conversation_as_read(
    conversation_id: UUID,
    read_data: MarkAsReadRequest,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    管理人用: メッセージを既読にする
    """
    conversation = conversations_crud.get_conversation_by_id(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation.type != ConversationType.DELUSION:
        raise HTTPException(status_code=403, detail="Not a delusion conversation")

    conversations_crud.mark_as_read(
        db=db,
        conversation_id=conversation_id,
        user_id=current_admin.id,
        message_id=read_data.message_id
    )

    return {"status": "success", "message": "Marked as read"}


@router.delete("/conversations/delusion/{conversation_id}/messages/{message_id}")
def delete_message(
    conversation_id: UUID,
    message_id: UUID,
    current_admin: Admins = Depends(get_current_admin_user),
    db: Session = Depends(get_db)
):
    """
    管理人用: メッセージを削除
    """
    conversation = conversations_crud.get_conversation_by_id(db, conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conversation.type != ConversationType.DELUSION:
        raise HTTPException(status_code=403, detail="Not a delusion conversation")

    message = conversations_crud.get_message_by_id(db, message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    if message.conversation_id != conversation_id:
        raise HTTPException(status_code=400, detail="Message does not belong to this conversation")

    success = conversations_crud.delete_message(db, message_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete message")

    return {"status": "success", "message": "Message deleted"}
