from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import Optional, List, Tuple
from uuid import UUID
from datetime import datetime, timezone, timedelta

from app.core.logger import Logger
from app.models.conversations import Conversations
from app.models.conversation_messages import ConversationMessages
from app.models.conversation_participants import ConversationParticipants
from app.models.user import Users
from app.models.admins import Admins
from app.constants.enums import ConversationType, ParticipantType
from app.models.profiles import Profiles
from app.constants.messages import WelcomeMessage

logger = Logger.get_logger()
# ========== 会話管理 ==========


def get_or_create_delusion_conversation(db: Session, user_id: UUID) -> Conversations:
    """
    妄想メッセージ用の会話を取得または作成する
    - 1ユーザーにつき1つの管理人トークルーム
    - 新規作成時は自動的にウェルカムメッセージを挿入
    """
    # 既存の妄想メッセージ会話を検索
    participant = (
        db.query(ConversationParticipants)
        .join(Conversations)
        .filter(
            ConversationParticipants.user_id == user_id,
            Conversations.type == ConversationType.DELUSION,
            Conversations.is_active == True,
        )
        .first()
    )

    if participant:
        participant.joined_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(participant)
        return participant.conversation

    # 新規作成
    conversation = Conversations(type=ConversationType.DELUSION, is_active=True)
    db.add(conversation)
    db.flush()

    # ユーザーを参加者として追加
    participant = ConversationParticipants(
        conversation_id=conversation.id,
        user_id=user_id,
        participant_id=user_id,
        participant_type=ParticipantType.USER,
        role=1,  # 通常ユーザー
    )
    db.add(participant)
    db.flush()

    # ウェルカムメッセージを自動挿入（システムメッセージ）
    base_timestamp = datetime.utcnow()
    welcome_message = ConversationMessages(
        conversation_id=conversation.id,
        sender_user_id=None,  # システムメッセージはsender_user_idをNULLに
        type=0,  # システムメッセージタイプ
        body_text=WelcomeMessage.MESSAGE,
        moderation=1,  # 自動承認
        created_at=base_timestamp,
    )
    db.add(welcome_message)
    db.flush()

    # 管理人メッセージを挿入（管理人が存在しない場合はシステムメッセージとして挿入）
    admin = (
        db.query(Admins)
        .filter(Admins.status == 1, Admins.deleted_at.is_(None))
        .order_by(Admins.created_at.asc())
        .first()
    )

    admin_message = ConversationMessages(
        conversation_id=conversation.id,
        sender_user_id=None if admin is None else None,
        sender_admin_id=admin.id if admin else None,
        type=1 if admin else 0,
        body_text=WelcomeMessage.SECOND_MESSAGE,
        moderation=1,  # 自動承認
        created_at=base_timestamp + timedelta(microseconds=1),
    )
    db.add(admin_message)
    db.flush()

    # 会話の最終メッセージ情報を更新
    last_message = admin_message or welcome_message
    conversation.last_message_id = last_message.id
    conversation.last_message_at = last_message.created_at

    db.commit()
    db.refresh(conversation)

    return conversation


def get_conversation_by_id(
    db: Session, conversation_id: UUID
) -> Optional[Conversations]:
    """会話IDで会話を取得"""
    return (
        db.query(Conversations)
        .filter(Conversations.id == conversation_id, Conversations.is_active == True)
        .first()
    )


def is_user_in_conversation(db: Session, conversation_id: UUID, user_id: UUID) -> bool:
    """ユーザーが会話の参加者かどうかを確認"""
    participant = (
        db.query(ConversationParticipants)
        .filter(
            ConversationParticipants.conversation_id == conversation_id,
            ConversationParticipants.user_id == user_id,
        )
        .first()
    )
    return participant is not None


# ========== メッセージ管理 ==========


def create_message(
    db: Session,
    conversation_id: UUID,
    sender_user_id: UUID | None = None,
    sender_admin_id: UUID | None = None,
    body_text: str = "",
) -> ConversationMessages:
    """
    メッセージを作成
    - sender_user_id と sender_admin_id の両方が None の場合はシステムメッセージ
    - sender_user_id が指定されている場合はユーザーメッセージ
    - sender_admin_id が指定されている場合は管理者メッセージ
    """
    message = ConversationMessages(
        conversation_id=conversation_id,
        sender_user_id=sender_user_id,
        sender_admin_id=sender_admin_id,
        type=1,  # テキストメッセージ
        body_text=body_text,
        moderation=1,  # デフォルト: 承認済み
    )
    db.add(message)
    db.flush()

    # 会話の最終メッセージ情報を更新
    conversation = (
        db.query(Conversations).filter(Conversations.id == conversation_id).first()
    )
    if conversation:
        conversation.last_message_id = message.id
        conversation.last_message_at = message.created_at

    db.commit()
    db.refresh(message)
    return message


def get_messages_by_conversation(
    db: Session, conversation_id: UUID, skip: int = 0, limit: int = 50
) -> List[
    Tuple[ConversationMessages, Optional[Users], Optional[Profiles], Optional[Admins]]
]:
    """
    会話のメッセージ一覧を取得（送信者情報含む）
    古い順にソート
    システムメッセージ（sender_user_id/sender_admin_id共にNULL）も含む
    Returns: (message, user, profile, admin) のタプルリスト
    """
    messages = (
        db.query(ConversationMessages, Users, Profiles, Admins)
        .join(Users, ConversationMessages.sender_user_id == Users.id, isouter=True)
        .join(Profiles, Users.id == Profiles.user_id, isouter=True)
        .join(Admins, ConversationMessages.sender_admin_id == Admins.id, isouter=True)
        .filter(
            ConversationMessages.conversation_id == conversation_id,
            ConversationMessages.deleted_at.is_(None),
        )
        .order_by(ConversationMessages.created_at.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return messages


def get_message_by_id(db: Session, message_id: UUID) -> Optional[ConversationMessages]:
    """メッセージIDでメッセージを取得"""
    return (
        db.query(ConversationMessages)
        .filter(
            ConversationMessages.id == message_id,
            ConversationMessages.deleted_at.is_(None),
        )
        .first()
    )


def delete_message(db: Session, message_id: UUID) -> bool:
    """メッセージを論理削除"""
    message = get_message_by_id(db, message_id)
    if not message:
        return False

    message.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return True


# ========== 既読管理 ==========


def mark_as_read(db: Session, conversation_id: UUID, user_id: UUID, message_id: UUID):
    """メッセージを既読にする（管理人用）"""
    participant = (
        db.query(ConversationParticipants)
        .filter(
            ConversationParticipants.conversation_id == conversation_id,
            ConversationParticipants.user_id == user_id,
        )
        .first()
    )

    if participant:
        participant.last_read_message_id = message_id
        db.commit()


def get_unread_count(db: Session, conversation_id: UUID, user_id: UUID) -> int:
    """未読メッセージ数を取得（管理人用）"""
    participant = (
        db.query(ConversationParticipants)
        .filter(
            ConversationParticipants.conversation_id == conversation_id,
            ConversationParticipants.user_id == user_id,
        )
        .first()
    )
    if not participant:
        return 0

    # 最後に読んだメッセージIDがない場合は全メッセージが未読
    if not participant.last_read_message_id:
        return (
            db.query(ConversationMessages)
            .filter(
                ConversationMessages.conversation_id == conversation_id,
                ConversationMessages.deleted_at.is_(None),
            )
            .count()
        )

    # 最後に読んだメッセージ以降のメッセージ数をカウント
    last_read_message = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id == participant.last_read_message_id)
        .first()
    )

    if not last_read_message:
        return 0

    unread_count = (
        db.query(ConversationMessages)
        .filter(
            ConversationMessages.conversation_id == conversation_id,
            ConversationMessages.created_at > last_read_message.created_at,
            ConversationMessages.deleted_at.is_(None),
        )
        .count()
    )

    return unread_count


# ========== 管理人用: 会話一覧 ==========


def get_all_delusion_conversations_for_admin(
    db: Session, skip: int = 0, limit: int = 50
) -> List[dict]:
    """
    管理人用: すべての妄想メッセージ会話一覧を取得
    未読カウント、最後のメッセージなどを含む
    """
    # 妄想メッセージタイプの全会話を取得
    conversations = (
        db.query(
            Conversations.id,
            Conversations.last_message_at,
            Conversations.created_at,
            ConversationParticipants.user_id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
        )
        .join(
            ConversationParticipants,
            Conversations.id == ConversationParticipants.conversation_id,
        )
        .join(Users, ConversationParticipants.user_id == Users.id)
        .join(ConversationMessages, Conversations.last_message_id == ConversationMessages.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(
            Conversations.type == ConversationType.DELUSION,
            Conversations.is_active == True,
            ConversationMessages.sender_admin_id.is_(None),
        )
        .order_by(desc(Conversations.last_message_at))
        .offset(skip)
        .limit(limit)
        .all()
    )

    result = []
    for conv in conversations:
        # 最後のメッセージを取得
        last_message = None
        if conv.last_message_at:
            last_message_obj = (
                db.query(ConversationMessages)
                .join(Conversations)
                .filter(Conversations.id == conv.id)
                .order_by(desc(ConversationMessages.created_at))
                .first()
            )

            if last_message_obj:
                last_message = last_message_obj.body_text

        result.append(
            {
                "id": conv.id,
                "user_id": conv.user_id,
                "user_username": conv.profile_name,
                "user_profile_name": conv.profile_name,
                "user_avatar": conv.avatar_url,
                "last_message_text": last_message,
                "last_message_at": conv.last_message_at,
                "unread_count": 0,  # 後で実装可能
                "created_at": conv.created_at,
            }
        )

    return result


def get_new_conversations_unread(db: Session, user_id: UUID) -> int:
    """
    新着メッセージ数を取得
    """
    try:
        participant = (
            db.query(
                ConversationParticipants,
                Conversations.last_message_at.label("last_message_at"),
                ConversationMessages,
            )
            .join(
                Conversations,
                ConversationParticipants.conversation_id == Conversations.id,
            )
            .join(
                ConversationMessages,
                Conversations.last_message_id == ConversationMessages.id,
            )
            .filter(ConversationParticipants.user_id == user_id)
            .first()
        )
        if (participant.ConversationMessages.sender_admin_id is not None) and (
            participant.ConversationParticipants.joined_at
            < participant.ConversationMessages.created_at
        ):
            return True
        return False
    except Exception as e:
        logger.error(f"Get new conversations unread error: {e}")
        return False
