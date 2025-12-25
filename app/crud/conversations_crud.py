from sqlalchemy.orm import Session
from sqlalchemy import desc, exists, or_, func
from typing import Optional, List, Tuple
from uuid import UUID
from datetime import datetime, timezone, timedelta

from app.core.logger import Logger
from app.models.conversations import Conversations
from app.models.conversation_messages import ConversationMessages
from app.models.conversation_participants import ConversationParticipants
from app.models.user import Users
from app.models.admins import Admins
from app.constants.enums import ConversationType, ParticipantType, ConversationMessageType, ConversationMessageStatus
from app.models.profiles import Profiles
from app.constants.messages import WelcomeMessage
import os
BASE_URL = os.getenv("CDN_BASE_URL")

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


def _update_conversation_last_message(
    db: Session, conversation_id: UUID, message: ConversationMessages
) -> None:
    """
    会話の最終メッセージ情報を更新する共通関数
    """
    conversation = (
        db.query(Conversations).filter(Conversations.id == conversation_id).first()
    )
    if conversation:
        conversation.last_message_id = message.id
        conversation.last_message_at = message.created_at


def _create_and_save_message(
    db: Session,
    conversation_id: UUID,
    message_type: int,
    sender_user_id: UUID | None = None,
    sender_admin_id: UUID | None = None,
    body_text: str = "",
    status: int = 1,
    scheduled_at: datetime | None = None,
    group_by: str | None = None,
) -> ConversationMessages:
    """
    メッセージを作成・保存する共通関数
    """
    message = ConversationMessages(
        conversation_id=conversation_id,
        sender_user_id=sender_user_id,
        sender_admin_id=sender_admin_id,
        type=message_type,
        body_text=body_text,
        moderation=1,  # デフォルト: 承認済み
        status=status,
        scheduled_at=scheduled_at,
        group_by=group_by,
    )
    db.add(message)
    db.flush()

    # 会話の最終メッセージ情報を更新
    _update_conversation_last_message(db, conversation_id, message)

    db.commit()
    db.refresh(message)
    return message


def create_message(
    db: Session,
    conversation_id: UUID,
    sender_user_id: UUID | None = None,
    sender_admin_id: UUID | None = None,
    body_text: str = "",
    status: int = 1,
    group_by: str | None = None,
) -> ConversationMessages:
    """
    メッセージを作成
    - sender_user_id と sender_admin_id の両方が None の場合はシステムメッセージ
    - sender_user_id が指定されている場合はユーザーメッセージ
    - sender_admin_id が指定されている場合は管理者メッセージ
    - status: メッセージステータス（0=無効、1=有効）
    """
    return _create_and_save_message(
        db=db,
        conversation_id=conversation_id,
        message_type=ConversationMessageType.USER,
        sender_user_id=sender_user_id,
        sender_admin_id=sender_admin_id,
        body_text=body_text,
        status=status,
        group_by=group_by,
    )


def create_bulk_message(
    db: Session,
    conversation_id: UUID,
    sender_user_id: UUID | None = None,
    sender_admin_id: UUID | None = None,
    body_text: str = "",
    status: int = 1,
    scheduled_at: datetime | None = None,
    group_by: str = "",
) -> ConversationMessages:
    """
    一斉送信メッセージを作成
    """
    return _create_and_save_message(
        db=db,
        conversation_id=conversation_id,
        message_type=ConversationMessageType.BULK,
        sender_user_id=sender_user_id,
        sender_admin_id=sender_admin_id,
        body_text=body_text,
        status=status,
        scheduled_at=scheduled_at,
        group_by=group_by,
    )


def create_chip_message(
    db: Session,
    conversation_id: UUID,
    sender_user_id: UUID | None = None,
    sender_admin_id: UUID | None = None,
    body_text: str = "",
    status: int = 1,
) -> ConversationMessages:
    """
    チップメッセージを作成
    """
    return _create_and_save_message(
        db=db,
        conversation_id=conversation_id,
        message_type=ConversationMessageType.CHIP,
        sender_user_id=sender_user_id,
        sender_admin_id=sender_admin_id,
        body_text=body_text,
        status=status,
    )

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
            or_(
                ConversationMessages.status != 0,
                ConversationMessages.status.is_(None),
            ),
            ConversationMessages.deleted_at.is_(None),
            ConversationMessages.status != ConversationMessageStatus.PENDING,
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
    """メッセージを既読にする"""
    from app.core.logger import Logger
    logger = Logger.get_logger()

    # 既存のparticipantレコードを取得
    participant = (
        db.query(ConversationParticipants)
        .filter(
            ConversationParticipants.conversation_id == conversation_id,
            ConversationParticipants.user_id == user_id,
        )
        .first()
    )

    if participant:
        logger.info(f"Marking message {message_id} as read for user {user_id} in conversation {conversation_id}")
        participant.last_read_message_id = message_id
        participant.updated_at = func.now()
        db.commit()
        db.refresh(participant)
        logger.info(f"Successfully marked message as read. last_read_message_id={participant.last_read_message_id}")
    else:
        logger.warning(f"Participant not found for user {user_id} in conversation {conversation_id}")


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
    一度でもユーザーからメッセージがあった会話を表示
    """
    # サブクエリ: 会話内にユーザーからのメッセージが存在するかチェック
    has_user_message = exists().where(
        ConversationMessages.conversation_id == Conversations.id,
        ConversationMessages.sender_user_id.isnot(None),
        ConversationMessages.deleted_at.is_(None)
    )

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
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(
            Conversations.type == ConversationType.DELUSION,
            Conversations.is_active == True,
            has_user_message,  # 一度でもユーザーメッセージがある会話のみ
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
                "user_username": conv.username,
                "user_profile_name": conv.profile_name,
                "user_avatar": f"{BASE_URL}/{conv.avatar_url}" if conv.avatar_url else None,
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
                isouter=True,
            )
            .filter(ConversationParticipants.user_id == user_id)
            .first()
        )
        if participant is None:
            return False
        
        # タプルの場合、インデックスでアクセス
        # participant[0] = ConversationParticipants
        # participant[1] = last_message_at
        # participant[2] = ConversationMessages
        if len(participant) < 3 or participant[2] is None:
            return False
        
        conversation_messages = participant[2]
        conversation_participants = participant[0]
        
        if (conversation_messages.sender_admin_id is not None) and (
            conversation_participants.joined_at
            < conversation_messages.created_at
        ):
            return True
        return False
    except Exception as e:
        logger.error(f"Get new conversations unread error: {e}", exc_info=True)
        return False


def get_user_conversations(
    db: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20,
    search: Optional[str] = None,
    sort: str = "last_message_desc",
    unread_only: bool = False,
) -> Tuple[List[dict], int]:
    """
    ログインユーザーが参加しているtype=2の会話リストを取得

    Args:
        db: データベースセッション
        user_id: ログインユーザーID
        skip: スキップ件数
        limit: 取得件数
        search: 検索キーワード（相手の名前で検索）
        sort: ソート順（last_message_desc, last_message_asc）
        unread_only: 未読のみフィルター

    Returns:
        Tuple[会話リスト, 全体件数]
    """
    # 基本クエリ: ユーザーが参加しているtype=2の会話
    query = (
        db.query(
            Conversations.id.label("conversation_id"),
            Conversations.last_message_at,
            Conversations.created_at,
            ConversationParticipants.last_read_message_id,
            Users.id.label("partner_user_id"),
            Users.profile_name.label("partner_name"),
            Profiles.avatar_url.label("partner_avatar"),
        )
        .join(
            ConversationParticipants,
            Conversations.id == ConversationParticipants.conversation_id
        )
        .filter(
            ConversationParticipants.user_id == user_id,
            Conversations.type == ConversationType.DM,  # type=2: クリエイターとユーザーのDM
            Conversations.is_active == True,
            Conversations.deleted_at.is_(None),
        )
    )

    # 相手ユーザー情報を取得するために、もう一つのConversationParticipantsとJOIN
    # self-join を使用して相手を特定
    from sqlalchemy.orm import aliased
    PartnerParticipant = aliased(ConversationParticipants)

    query = query.join(
        PartnerParticipant,
        (PartnerParticipant.conversation_id == Conversations.id) &
        (PartnerParticipant.user_id != user_id)
    ).join(
        Users,
        Users.id == PartnerParticipant.user_id
    ).outerjoin(
        Profiles,
        Profiles.user_id == Users.id
    )

    # 検索フィルター（相手の名前で検索）
    if search:
        query = query.filter(
            Users.profile_name.ilike(f"%{search}%")
        )

    # 未読フィルター
    if unread_only:
        query = query.filter(
            (ConversationParticipants.last_read_message_id.is_(None)) |
            (ConversationParticipants.last_read_message_id != Conversations.last_message_id)
        )

    # 最終メッセージがある会話のみをカウントするためのサブクエリ
    messages_with_valid_status = (
        db.query(ConversationMessages.conversation_id)
        .filter(
            ConversationMessages.deleted_at.is_(None),
            or_(
                ConversationMessages.status != 0,
                ConversationMessages.status.is_(None)
            ),
            ConversationMessages.status != ConversationMessageStatus.PENDING,
        )
        .group_by(ConversationMessages.conversation_id)
        .subquery()
    )
    
    # 最終メッセージがある会話のみをフィルタリング
    query_with_message = query.filter(
        Conversations.id.in_(
            db.query(messages_with_valid_status.c.conversation_id)
        )
    )
    
    # 全体件数を取得（最終メッセージがある会話のみ）
    total = query_with_message.count()

    # ソート
    if sort == "last_message_asc":
        query = query.order_by(Conversations.last_message_at.asc())
    else:  # last_message_desc (デフォルト)
        query = query.order_by(Conversations.last_message_at.desc())

    # ページネーション
    conversations = query.offset(skip).limit(limit).all()

    # レスポンス構築
    result = []
    for conv in conversations:
        # 最終メッセージを取得
        last_message_text = None
        last_message = None
        if conv.conversation_id:
            last_message = (
                db.query(ConversationMessages)
                .filter(
                    ConversationMessages.conversation_id == conv.conversation_id,
                    ConversationMessages.deleted_at.is_(None),
                    or_(
                        ConversationMessages.status != 0,
                        ConversationMessages.status.is_(None)
                    ),
                    ConversationMessages.status != ConversationMessageStatus.PENDING,
                )
                .order_by(ConversationMessages.created_at.desc())
                .first()
            )
            if last_message:
                last_message_text = last_message.body_text

        # 最終メッセージがない場合は除外
        if not last_message:
            continue

        # 未読件数を計算
        unread_count = 0
        if conv.last_read_message_id:
            unread_count = (
                db.query(ConversationMessages)
                .filter(
                    ConversationMessages.conversation_id == conv.conversation_id,
                    ConversationMessages.created_at > (
                        db.query(ConversationMessages.created_at)
                        .filter(ConversationMessages.id == conv.last_read_message_id)
                        .scalar_subquery()
                    ),
                    ConversationMessages.sender_user_id != user_id,
                    ConversationMessages.deleted_at.is_(None),
                    ConversationMessages.status != ConversationMessageStatus.PENDING,  # status=2を除外
                    ConversationMessages.status != ConversationMessageStatus.INACTIVE,  # status=0を除外
                )
                .count()
            )
        else:
            # 最終既読メッセージIDがない場合は全メッセージを未読とする
            unread_count = (
                db.query(ConversationMessages)
                .filter(
                    ConversationMessages.conversation_id == conv.conversation_id,
                    ConversationMessages.sender_user_id != user_id,
                    ConversationMessages.deleted_at.is_(None),
                    ConversationMessages.status != ConversationMessageStatus.PENDING,  # status=2を除外
                    ConversationMessages.status != ConversationMessageStatus.INACTIVE,  # status=0を除外
                )
                .count()
            )

        result.append({
            "id": str(conv.conversation_id),
            "partner_user_id": str(conv.partner_user_id),
            "partner_name": conv.partner_name,
            "partner_avatar": f"{BASE_URL}/{conv.partner_avatar}" if conv.partner_avatar else None,
            "last_message_text": last_message_text,
            "last_message_at": conv.last_message_at,
            "unread_count": unread_count,
            "created_at": conv.created_at,
        })

    return result, total


def get_or_create_dm_conversation(
    db: Session, user_id_1: UUID, user_id_2: UUID
) -> Conversations:
    """
    2人のユーザー間のDM会話を取得または作成する

    Args:
        db: データベースセッション
        user_id_1: ユーザー1のID
        user_id_2: ユーザー2のID

    Returns:
        Conversations: 既存または新規作成されたDM会話
    """
    # 既存のDM会話を検索（type=2のconversationで、両方のユーザーが参加している）
    # サブクエリで2人目のユーザーが参加しているか確認
    from sqlalchemy import exists as sql_exists
    from sqlalchemy.orm import aliased

    # サブクエリ内で使用するためにエイリアスを作成
    Participant2 = aliased(ConversationParticipants)

    existing_conversation = (
        db.query(Conversations)
        .join(
            ConversationParticipants,
            ConversationParticipants.conversation_id == Conversations.id,
        )
        .filter(
            Conversations.type == ConversationType.DM,
            Conversations.is_active == True,
            Conversations.deleted_at.is_(None),
            ConversationParticipants.user_id == user_id_1,
        )
        .filter(
            sql_exists().where(
                Participant2.conversation_id == Conversations.id,
                Participant2.user_id == user_id_2,
            )
        )
        .first()
    )

    if existing_conversation:
        logger.info(
            f"Found existing DM conversation: {existing_conversation.id} between user1={user_id_1} and user2={user_id_2}"
        )
        return existing_conversation

    # 新規会話を作成
    conversation = Conversations(
        type=ConversationType.DM,
        is_active=True,
    )
    db.add(conversation)
    db.flush()

    # ユーザー1を参加者として追加
    participant_1 = ConversationParticipants(
        conversation_id=conversation.id,
        user_id=user_id_1,
        participant_id=user_id_1,
        participant_type=ParticipantType.USER,
        role=1,  # 通常ユーザー
    )
    db.add(participant_1)

    # ユーザー2を参加者として追加
    participant_2 = ConversationParticipants(
        conversation_id=conversation.id,
        user_id=user_id_2,
        participant_id=user_id_2,
        participant_type=ParticipantType.USER,
        role=1,  # 通常ユーザー
    )
    db.add(participant_2)
    db.flush()

    logger.info(
        f"Created new DM conversation: {conversation.id} between user1={user_id_1} and user2={user_id_2}"
    )

    db.commit()
    db.refresh(conversation)

    return conversation
