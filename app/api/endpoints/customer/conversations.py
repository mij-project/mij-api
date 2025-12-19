from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import cast
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from typing import List
from uuid import UUID

from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.crud import conversations_crud, user_crud, profile_crud, payments_crud, subscriptions_crud
from app.models.conversation_participants import ConversationParticipants
from app.models.payments import Payments
from app.models.subscriptions import Subscriptions
from app.models.plans import Plans
from app.constants.enums import PaymentType, PaymentStatus, SubscriptionStatus
from app.schemas.conversation import (
    MessageCreate,
    MessageResponse,
    ConversationResponse,
    ConversationMessagesResponse,
)
import os

router = APIRouter()

BASE_URL = os.getenv("CDN_BASE_URL")

# ========== 一般ユーザー用エンドポイント ==========


@router.get("/delusion", response_model=ConversationResponse)
def get_or_create_delusion_conversation(
    current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    妄想メッセージ会話を取得または作成
    - 1ユーザーにつき1つの管理人トークルーム
    - 自動で作成される
    """
    conversation = conversations_crud.get_or_create_delusion_conversation(
        db, current_user.id
    )

    return ConversationResponse(
        id=conversation.id,
        type=conversation.type,
        is_active=conversation.is_active,
        last_message_id=conversation.last_message_id,
        last_message_at=conversation.last_message_at,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        unread_count=0,
    )


@router.get("/delusion/messages", response_model=List[MessageResponse])
def get_delusion_messages(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    妄想メッセージの一覧を取得
    - 古い順にソート
    - 送信者情報（名前、アバター）を含む
    """
    # ユーザーの妄想メッセージ会話を取得
    conversation = conversations_crud.get_or_create_delusion_conversation(
        db, current_user.id
    )

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
            sender_avatar = (
                f"{BASE_URL}/{profile.avatar_url}" if profile.avatar_url else None
            )
            sender_profile_name = sender.profile_name
        elif admin:
            # 管理者メッセージの場合
            sender_username = "運営"
            sender_avatar = None
            sender_profile_name = "運営"

        response.append(
            MessageResponse(
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
                sender_profile_name=sender_profile_name,
            )
        )

    return response


@router.post("/delusion/messages", response_model=MessageResponse)
def send_delusion_message(
    message_data: MessageCreate,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    妄想メッセージを送信
    - テキストのみ対応
    """
    # ユーザーの妄想メッセージ会話を取得
    conversation = conversations_crud.get_or_create_delusion_conversation(
        db, current_user.id
    )

    # メッセージを作成
    message = conversations_crud.create_message(
        db=db,
        conversation_id=conversation.id,
        sender_user_id=current_user.id,
        body_text=message_data.body_text,
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
        sender_profile_name=current_user.profile_name,
    )


@router.get("/unread")
async def get_new_conversations_unread(
    current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    新着メッセージ数を取得
    """
    is_unread = conversations_crud.get_new_conversations_unread(db, current_user.id)
    return {"is_unread": is_unread}


@router.get("/conversations/list", response_model=List[ConversationResponse])
def get_conversations_list(
    current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    会話一覧を取得
    """
    conversations = conversations_crud.get_conversations_list(db, current_user.id)
    return conversations


@router.get("/list")
def get_user_conversations(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    search: str = Query(None),
    sort: str = Query("last_message_desc"),
    unread_only: bool = Query(False),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    ログインユーザーが参加しているtype=2の会話リストを取得

    Args:
        skip: スキップ件数（無限スクロール用）
        limit: 取得件数
        search: 検索キーワード（相手の名前で検索）
        sort: ソート順（last_message_desc, last_message_asc）
        unread_only: 未読のみフィルター

    Returns:
        会話リスト
    """
    conversations, total = conversations_crud.get_user_conversations(
        db=db,
        user_id=current_user.id,
        skip=skip,
        limit=limit,
        search=search,
        sort=sort,
        unread_only=unread_only,
    )

    return {
        "data": conversations,
        "total": total,
        "skip": skip,
        "limit": limit,
    }


# ========== 個別会話のメッセージAPI ==========


@router.get("/{conversation_id}/messages", response_model=ConversationMessagesResponse)
def get_conversation_messages(
    conversation_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    個別会話のメッセージ一覧を取得
    - ユーザーが参加している会話のみ取得可能
    - 古い順にソート
    - 相手のプロフィール情報も含む
    """
    # ユーザーがこの会話に参加しているか確認
    if not conversations_crud.is_user_in_conversation(db, conversation_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied to this conversation")

    # メッセージ一覧を取得
    messages = conversations_crud.get_messages_by_conversation(
        db, conversation_id, skip, limit
    )

    # 会話の参加者から相手のユーザー情報を取得
    partner_user_id = None
    partner_username = None
    partner_profile_name = None
    partner_avatar = None

    # conversation_participantsから相手のuser_idを取得
    participants = db.query(ConversationParticipants).filter(
        ConversationParticipants.conversation_id == conversation_id,
        ConversationParticipants.user_id != current_user.id
    ).first()


    if participants:
        partner_user_id = participants.user_id
        # 相手のユーザー情報とプロフィールを取得
        partner_user = user_crud.get_user_by_id(db, partner_user_id)
        if partner_user:
            partner_username = partner_user.profile_name
            partner_profile_name = partner_user.profile_name
            # プロフィールから相手のアバターを取得
            partner_profile = profile_crud.get_profile_by_user_id(db, partner_user_id)
            if partner_profile and partner_profile.avatar_url:
                partner_avatar = f"{BASE_URL}/{partner_profile.avatar_url}"

    # メッセージレスポンスを構築
    message_responses = []
    for message, sender, profile, admin in messages:
        # 送信者情報の判定
        sender_username = None
        sender_avatar = None
        sender_profile_name = None

        if sender and profile:
            # ユーザーメッセージの場合
            sender_username = sender.profile_name
            sender_avatar = (
                f"{BASE_URL}/{profile.avatar_url}" if profile.avatar_url else None
            )
            sender_profile_name = sender.profile_name
        elif admin:
            # 管理者メッセージの場合
            sender_username = "運営"
            sender_avatar = None
            sender_profile_name = "運営"

        message_responses.append(
            MessageResponse(
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
                sender_profile_name=sender_profile_name,
            )
        )

    # メッセージ送信権限の判定
    can_send_message = False
    if partner_user_id:
        # 条件1: チップ送信履歴の確認（双方向）
        has_chip_history = payments_crud.get_payment_by_user_id(db, current_user.id, partner_user_id, PaymentType.CHIP)

        # 条件2: DM解放プラン加入の確認
        # order_typeが1(plan_id)の場合のみ、order_idをUUIDにキャストしてplansテーブルと結合
        has_dm_plan = subscriptions_crud.get_subscription_by_user_id(db, current_user.id, partner_user_id)
        # どちらか一方を満たせばメッセージ送信可能
        can_send_message = has_chip_history or has_dm_plan

    return ConversationMessagesResponse(
        messages=message_responses,
        partner_user_id=partner_user_id,
        partner_username=partner_username,
        partner_profile_name=partner_profile_name,
        partner_avatar=partner_avatar,
        can_send_message=can_send_message,
    )


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
def send_conversation_message(
    conversation_id: UUID,
    message_data: MessageCreate,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    個別会話にメッセージを送信
    - ユーザーが参加している会話のみ送信可能
    """
    # ユーザーがこの会話に参加しているか確認
    if not conversations_crud.is_user_in_conversation(db, conversation_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied to this conversation")

    # メッセージを作成
    message = conversations_crud.create_message(
        db=db,
        conversation_id=conversation_id,
        sender_user_id=current_user.id,
        body_text=message_data.body_text,
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
        sender_username=current_user.profile_name,
        sender_avatar=None,  # TODO: プロフィールから取得
        sender_profile_name=current_user.profile_name,
    )


@router.post("/{conversation_id}/messages/{message_id}/read")
def mark_conversation_message_as_read(
    conversation_id: UUID,
    message_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    メッセージを既読にする
    - ユーザーが参加している会話のみ既読可能
    """
    # ユーザーがこの会話に参加しているか確認
    if not conversations_crud.is_user_in_conversation(db, conversation_id, current_user.id):
        raise HTTPException(status_code=403, detail="Access denied to this conversation")

    # 既読にする
    conversations_crud.mark_as_read(db, conversation_id, current_user.id, message_id)

    return {"status": "ok", "message": "Message marked as read"}


@router.get("/get-or-create/{partner_user_id}")
def get_or_create_conversation_with_user(
    partner_user_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    指定したユーザーとの会話を取得または作成
    - 既存の会話があればそれを返す
    - なければ新規作成して返す
    - 自分自身との会話は禁止
    """
    # 自分自身との会話は禁止
    if current_user.id == partner_user_id:
        raise HTTPException(status_code=400, detail="Cannot create conversation with yourself")

    # 既存の会話を取得または新規作成
    conversation = conversations_crud.get_or_create_dm_conversation(
        db=db,
        user_id_1=current_user.id,
        user_id_2=partner_user_id,
    )

    return {
        "conversation_id": str(conversation.id),
        "partner_user_id": str(partner_user_id),
    }