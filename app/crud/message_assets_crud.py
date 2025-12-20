# app/crud/message_assets_crud.py
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional, List, Tuple
from app.models.message_assets import MessageAssets
from app.constants.enums import MessageAssetStatus
from app.models.conversation_messages import ConversationMessages
from app.models.conversations import Conversations
from app.models.conversation_participants import ConversationParticipants
from app.models.profiles import Profiles

def create_message_asset(
    db: Session,
    message_id: UUID,
    asset_type: int,
    storage_key: str,
    status: int = MessageAssetStatus.PENDING,
) -> MessageAssets:
    """
    メッセージアセットを作成

    Args:
        db: データベースセッション
        message_id: メッセージID
        asset_type: アセットタイプ (1=画像, 2=動画)
        storage_key: S3ストレージキー
        status: ステータス (デフォルト: 0=審査待ち)

    Returns:
        作成されたMessageAssetsオブジェクト
    """
    message_asset = MessageAssets(
        message_id=message_id,
        asset_type=asset_type,
        storage_key=storage_key,
        status=status,
    )
    db.add(message_asset)
    db.commit()
    db.refresh(message_asset)
    return message_asset


def get_message_asset_by_id(db: Session, asset_id: UUID) -> Optional[MessageAssets]:
    """
    IDでメッセージアセットを取得

    Args:
        db: データベースセッション
        asset_id: アセットID

    Returns:
        MessageAssetsオブジェクト or None
    """
    return db.query(MessageAssets).filter(MessageAssets.id == asset_id).first()


def get_message_assets_by_message_id(db: Session, message_id: UUID) -> list[MessageAssets]:
    """
    メッセージIDでアセット一覧を取得

    Args:
        db: データベースセッション
        message_id: メッセージID

    Returns:
        MessageAssetsオブジェクトのリスト
    """
    return db.query(MessageAssets).filter(MessageAssets.message_id == message_id).all()


def get_pending_message_assets(
    db: Session, skip: int = 0, limit: int = 50
) -> list[MessageAssets]:
    """
    審査待ちのアセット一覧を取得（管理画面用）

    Args:
        db: データベースセッション
        skip: スキップ件数
        limit: 取得件数

    Returns:
        MessageAssetsオブジェクトのリスト
    """
    return (
        db.query(MessageAssets)
        .filter(MessageAssets.status == MessageAssetStatus.PENDING)
        .order_by(MessageAssets.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def approve_message_asset(db: Session, asset_id: UUID) -> Optional[MessageAssets]:
    """
    メッセージアセットを承認

    Args:
        db: データベースセッション
        asset_id: アセットID

    Returns:
        更新されたMessageAssetsオブジェクト or None
    """
    asset = db.query(MessageAssets).filter(MessageAssets.id == asset_id).first()
    if not asset:
        return None

    asset.status = MessageAssetStatus.APPROVED
    asset.reject_comments = None  # 承認時は拒否コメントをクリア
    db.commit()
    db.refresh(asset)
    return asset


def reject_message_asset(
    db: Session, asset_id: UUID, reject_comments: str
) -> Optional[MessageAssets]:
    """
    メッセージアセットを拒否

    Args:
        db: データベースセッション
        asset_id: アセットID
        reject_comments: 拒否理由コメント

    Returns:
        更新されたMessageAssetsオブジェクト or None
    """
    asset = db.query(MessageAssets).filter(MessageAssets.id == asset_id).first()
    if not asset:
        return None

    asset.status = MessageAssetStatus.REJECTED
    asset.reject_comments = reject_comments
    db.commit()
    db.refresh(asset)
    return asset


def delete_message_asset(db: Session, asset_id: UUID) -> bool:
    """
    メッセージアセットを削除

    Args:
        db: データベースセッション
        asset_id: アセットID

    Returns:
        削除成功の場合True、失敗の場合False
    """
    asset = db.query(MessageAssets).filter(MessageAssets.id == asset_id).first()
    if not asset:
        return False

    db.delete(asset)
    db.commit()
    return True


def get_user_message_assets(
    db: Session,
    user_id: UUID,
    status: Optional[int] = None,
    skip: int = 0,
    limit: int = 50
) -> list[MessageAssets]:
    """
    ユーザーが送信したメッセージアセット一覧を取得

    Args:
        db: データベースセッション
        user_id: ユーザーID
        status: アセットステータス（0=審査中, 1=承認済み, 2=拒否）
        skip: スキップ件数
        limit: 取得件数

    Returns:
        MessageAssetsオブジェクトのリスト
    """

    query = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.sender_user_id == user_id)
    )

    if status is not None:
        query = query.filter(MessageAssets.status == status)

    return (
        query.order_by(MessageAssets.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_message_assets_for_admin(
    db: Session,
    status: Optional[int] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[MessageAssets], int]:
    """
    管理者用：メッセージアセット一覧を取得（送信者・受信者情報含む）

    Args:
        db: データベースセッション
        status: アセットステータス（0=審査中, 1=承認済み, 2=拒否）
        skip: スキップ件数
        limit: 取得件数

    Returns:
        (MessageAssetsオブジェクトのリスト, 総件数)
    """
    query = db.query(MessageAssets)

    if status is not None:
        query = query.filter(MessageAssets.status == status)

    # 総件数を取得
    total = query.count()

    # ページネーション適用
    assets = (
        query.order_by(MessageAssets.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return assets, total


def get_message_asset_detail_for_admin(
    db: Session, asset_id: UUID
) -> Optional[dict]:
    """
    管理者用：メッセージアセット詳細を取得（送信者・受信者・メッセージ情報含む）

    Args:
        db: データベースセッション
        asset_id: アセットID

    Returns:
        詳細情報の辞書 or None
    """
    # アセットを取得
    asset = db.query(MessageAssets).filter(MessageAssets.id == asset_id).first()
    if not asset:
        return None

    # メッセージ情報を取得
    message = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id == asset.message_id)
        .first()
    )

    if not message:
        return None

    # 会話情報を取得
    conversation = (
        db.query(Conversations)
        .filter(Conversations.id == message.conversation_id)
        .first()
    )

    if not conversation:
        return None

    # 送信者の情報を取得
    sender_profile = (
        db.query(Profiles)
        .filter(Profiles.user_id == message.sender_user_id)
        .first()
    )

    # 受信者の情報を取得（送信者以外の参加者）
    recipient_participant = (
        db.query(ConversationParticipants)
        .filter(
            ConversationParticipants.conversation_id == conversation.id,
            ConversationParticipants.user_id != message.sender_user_id,
        )
        .first()
    )

    recipient_profile = None
    if recipient_participant:
        recipient_profile = (
            db.query(Profiles)
            .filter(Profiles.user_id == recipient_participant.user_id)
            .first()
        )

    # 詳細情報を辞書形式で返却
    return {
        "asset": asset,
        "message": message,
        "conversation": conversation,
        "sender_profile": sender_profile,
        "recipient_profile": recipient_profile,
    }


def resubmit_message_asset(
    db: Session,
    asset_id: UUID,
    new_storage_key: str,
    new_asset_type: int,
    message_text: Optional[str] = None
) -> Optional[MessageAssets]:
    """
    メッセージアセットを再申請

    Args:
        db: データベースセッション
        asset_id: アセットID
        new_storage_key: 新しいS3ストレージキー
        new_asset_type: 新しいアセットタイプ（1=画像, 2=動画）
        message_text: メッセージ本文（オプション）

    Returns:
        更新されたMessageAssetsオブジェクト or None
    """
    asset = db.query(MessageAssets).filter(MessageAssets.id == asset_id).first()
    if not asset:
        return None

    # ステータスが拒否（REJECTED=2）でない場合は再申請できない
    if asset.status != MessageAssetStatus.REJECTED:
        return None

    # アセット情報を更新
    asset.storage_key = new_storage_key
    asset.asset_type = new_asset_type
    asset.status = MessageAssetStatus.RESUBMIT  # ステータスを再申請（3）に変更
    asset.reject_comments = None  # 拒否コメントをクリア

    # メッセージ本文も更新する場合
    if message_text is not None:
        message = (
            db.query(ConversationMessages)
            .filter(ConversationMessages.id == asset.message_id)
            .first()
        )
        if message:
            message.body_text = message_text

    db.commit()
    db.refresh(asset)
    return asset
