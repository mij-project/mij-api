# app/crud/message_assets_crud.py
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional, List, Tuple
from datetime import datetime
from app.models.message_assets import MessageAssets
from app.constants.enums import MessageAssetStatus, ConversationMessageStatus, ConversationMessageType
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


def approve_message_asset_by_group_by(
    db: Session, group_by: str
) -> Optional[MessageAssets]:
    """
    group_byでグループ化されたメッセージアセットをすべて承認
    ConversationMessages.group_byでフィルタリング

    Args:
        db: データベースセッション
        group_by: グループ化キー

    Returns:
        更新された代表的なMessageAssetsオブジェクト or None
    """
    # 同じgroup_byを持つすべてのアセットを取得（ConversationMessages.group_byでフィルタリング）
    assets = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .all()
    )
    
    if not assets:
        return None
    
    # すべてのアセットを承認
    for asset in assets:
        asset.status = MessageAssetStatus.APPROVED
        asset.reject_comments = None  # 承認時は拒否コメントをクリア
    
    db.commit()
    
    # 代表的なアセット1件を返す（最初に作成されたもの）
    representative_asset = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )
    
    if representative_asset:
        db.refresh(representative_asset)
    
    return representative_asset


def reject_message_asset_by_group_by(
    db: Session, group_by: str, reject_comments: str
) -> Optional[MessageAssets]:
    """
    group_byでグループ化されたメッセージアセットをすべて拒否
    ConversationMessages.group_byでフィルタリング

    Args:
        db: データベースセッション
        group_by: グループ化キー
        reject_comments: 拒否理由コメント

    Returns:
        更新された代表的なMessageAssetsオブジェクト or None
    """
    # 同じgroup_byを持つすべてのアセットを取得（ConversationMessages.group_byでフィルタリング）
    assets = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .all()
    )
    
    if not assets:
        return None
    
    # すべてのアセットを拒否
    for asset in assets:
        asset.status = MessageAssetStatus.REJECTED
        asset.reject_comments = reject_comments
    
    db.commit()
    
    # 代表的なアセット1件を返す（最初に作成されたもの）
    representative_asset = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )
    
    if representative_asset:
        db.refresh(representative_asset)
    
    return representative_asset


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
) -> List[dict]:
    """
    ユーザーが送信したメッセージアセット一覧を取得（group_byでグループ化）

    Args:
        db: データベースセッション
        user_id: ユーザーID
        status: アセットステータス（0=審査中, 1=承認済み, 2=拒否）
        skip: スキップ件数
        limit: 取得件数

    Returns:
        グループ化されたアセット情報のリスト
        各要素は {"group_by": str, "asset": MessageAssets, "message": ConversationMessages} の形式
        各グループから代表的なアセット1件のみを返す
    """
    from sqlalchemy import func
    
    # ConversationMessages.group_byでグループ化
    group_by_key = ConversationMessages.group_by
    
    # 総グループ数を取得（group_byがNULLでないもののみ）
    count_query = (
        db.query(func.count(func.distinct(group_by_key)))
        .select_from(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.group_by.isnot(None)
        )
    )
    
    if status is not None:
        count_query = count_query.filter(MessageAssets.status == status)
    
    # group_byでグループ化して、各グループの最初のアセットのcreated_atでソート
    subquery = (
        db.query(
            group_by_key.label("group_by"),
            func.min(MessageAssets.created_at).label("min_created_at")
        )
        .select_from(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.group_by.isnot(None)
        )
    )
    
    if status is not None:
        subquery = subquery.filter(MessageAssets.status == status)
    
    subquery = (
        subquery.group_by(group_by_key)
        .order_by(func.min(MessageAssets.created_at).desc())
        .offset(skip)
        .limit(limit)
        .subquery()
    )
    
    # 各グループのgroup_by値と最小created_atを取得
    group_by_list = (
        db.query(subquery.c.group_by, subquery.c.min_created_at)
        .all()
    )
    
    if not group_by_list:
        return []
    
    # 各グループから代表アセット1件を取得（created_atが最小のもの）
    assets = []
    for group_by, min_created_at in group_by_list:
        asset_query = (
            db.query(MessageAssets)
            .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
            .filter(
                ConversationMessages.group_by == group_by,
                MessageAssets.created_at == min_created_at,
                ConversationMessages.sender_user_id == user_id
            )
        )
        if status is not None:
            asset_query = asset_query.filter(MessageAssets.status == status)
        
        asset = asset_query.order_by(MessageAssets.created_at.asc()).first()
        if asset:
            assets.append(asset)
    
    # メッセージIDのリストを取得
    message_ids = list(set([asset.message_id for asset in assets]))
    
    # メッセージ情報を一括取得
    messages = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id.in_(message_ids))
        .all()
    )
    message_dict = {msg.id: msg for msg in messages}
    
    # グループ化キーを計算してasset_dictを作成
    asset_dict = {}
    for asset in assets:
        message = message_dict.get(asset.message_id)
        if message and message.group_by:
            group_key = message.group_by
            asset_dict[group_key] = asset
    
    # グループごとに整理（代表アセット1件のみ）
    grouped_data = []
    for group_by, min_created_at in group_by_list:
        asset = asset_dict.get(group_by)
        if not asset:
            continue
        
        message = message_dict.get(asset.message_id)
        
        grouped_data.append({
            "group_by": group_by,
            "asset": asset,
            "message": message
        })
    
    # ソート順を保持（min_created_atの降順）
    sorted_groups = sorted(
        grouped_data,
        key=lambda x: x["asset"].created_at if x["asset"] else datetime.min,
        reverse=True
    )
    
    return sorted_groups


def get_message_assets_for_admin(
    db: Session,
    status: Optional[int] = None,
    skip: int = 0,
    limit: int = 50
) -> Tuple[List[dict], int]:
    """
    管理者用：メッセージアセット一覧を取得（group_byでグループ化、メッセージ情報含む）
    ConversationMessages.group_byが存在する場合はそれでグループ化

    Args:
        db: データベースセッション
        status: アセットステータス（0=審査中, 1=承認済み, 2=拒否）
        skip: スキップ件数
        limit: 取得件数

    Returns:
        (グループ化されたアセット情報のリスト, 総グループ数)
        各要素は {"group_by": str, "asset": MessageAssets, "message": ConversationMessages} の形式
        各グループから代表的なアセット1件のみを返す
    """
    from sqlalchemy import func
    
    # ConversationMessagesとJOINして、ConversationMessages.group_byでグループ化
    # group_byがNULLの場合はグループ化されない（個別に扱われる）
    group_by_key = ConversationMessages.group_by
    
    # 総グループ数を取得（group_byがNULLでないもののみ）
    count_query = (
        db.query(func.count(func.distinct(group_by_key)))
        .select_from(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by.isnot(None))
    )
    if status is not None:
        count_query = count_query.filter(MessageAssets.status == status)
    total = count_query.scalar()
    
    # group_byでグループ化して、各グループの最初のアセットのcreated_atでソート
    # 各グループから代表的なアセット1件（最初に作成されたもの）を取得
    subquery = (
        db.query(
            group_by_key.label("group_by"),
            func.min(MessageAssets.created_at).label("min_created_at")
        )
        .select_from(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by.isnot(None))
    )
    
    if status is not None:
        subquery = subquery.filter(MessageAssets.status == status)
    
    subquery = (
        subquery.group_by(group_by_key)
        .order_by(func.min(MessageAssets.created_at).desc())
        .offset(skip)
        .limit(limit)
        .subquery()
    )
    
    # 各グループのgroup_by値と最小created_atを取得
    group_by_list = (
        db.query(subquery.c.group_by, subquery.c.min_created_at)
        .all()
    )
    
    if not group_by_list:
        return [], total
    
    # 各グループから代表アセット1件を取得（created_atが最小のもの）
    assets = []
    for group_by, min_created_at in group_by_list:
        # group_byキーに一致するアセットを取得
        asset_query = (
            db.query(MessageAssets)
            .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
            .filter(
                ConversationMessages.group_by == group_by,
                MessageAssets.created_at == min_created_at
            )
        )
        if status is not None:
            asset_query = asset_query.filter(MessageAssets.status == status)
        
        asset = asset_query.order_by(MessageAssets.created_at.asc()).first()
        if asset:
            assets.append(asset)
    
    # メッセージIDのリストを取得
    message_ids = list(set([asset.message_id for asset in assets]))
    
    # メッセージ情報を一括取得
    messages = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id.in_(message_ids))
        .all()
    )
    message_dict = {msg.id: msg for msg in messages}
    
    # グループ化キーを計算してasset_dictを作成
    asset_dict = {}
    for asset in assets:
        message = message_dict.get(asset.message_id)
        if message and message.group_by:
            group_key = message.group_by
            asset_dict[group_key] = asset
    
    # グループごとに整理（代表アセット1件のみ）
    grouped_data = []
    for group_by, min_created_at in group_by_list:
        asset = asset_dict.get(group_by)
        if not asset:
            continue
        
        message = message_dict.get(asset.message_id)
        
        grouped_data.append({
            "group_by": group_by,
            "asset": asset,
            "message": message
        })
    
    # ソート順を保持（min_created_atの降順）
    sorted_groups = sorted(
        grouped_data,
        key=lambda x: x["asset"].created_at if x["asset"] else datetime.min,
        reverse=True
    )
    
    return sorted_groups, total


def get_message_asset_detail_by_group_by_for_user(
    db: Session, group_by: str, user_id: UUID
) -> Optional[dict]:
    """
    ユーザー用：group_byでメッセージアセット詳細を取得（メッセージ情報含む）
    message_assetsがない場合でも、メッセージ情報を返す

    Args:
        db: データベースセッション
        group_by: グループ化キー
        user_id: ユーザーID（送信者の確認用）

    Returns:
        詳細情報の辞書 or None
    """
    # まずconversation_messages.group_byから代表的なメッセージを取得
    message = (
        db.query(ConversationMessages)
        .filter(
            ConversationMessages.group_by == group_by,
            ConversationMessages.sender_user_id == user_id
        )
        .order_by(ConversationMessages.created_at.asc())
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

    # message_assetsを取得（存在しない場合はNone）
    asset = (
        db.query(MessageAssets)
        .filter(MessageAssets.message_id == message.id)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )

    # 詳細情報を辞書形式で返却（assetはNoneの可能性あり）
    return {
        "asset": asset,  # Noneの可能性あり
        "message": message,
        "conversation": conversation,
    }


def get_message_asset_detail_by_group_by_for_admin(
    db: Session, group_by: str
) -> Optional[dict]:
    """
    管理者用：group_byでメッセージアセット詳細を取得（送信者・受信者・メッセージ情報含む）
    ConversationMessages.group_byでフィルタリング

    Args:
        db: データベースセッション
        group_by: グループ化キー

    Returns:
        詳細情報の辞書 or None
    """
    # group_byでグループ化されたアセットから代表的な1件を取得（最初に作成されたもの）
    # ConversationMessages.group_byでフィルタリング
    asset = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )
    
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


def get_user_message_assets_counts(
    db: Session,
    user_id: UUID
) -> dict:
    """
    ユーザーのメッセージアセットのステータス別カウントを取得（group_byでグループ化）

    Args:
        db: データベースセッション
        user_id: ユーザーID

    Returns:
        {'pending_count': int, 'reject_count': int, 'reserved_count': int}
    """
    from sqlalchemy import func

    # PENDING と RESUBMIT のグループ数をカウント（ConversationMessages.group_byで）
    pending_subquery = (
        db.query(ConversationMessages.group_by)
        .select_from(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.group_by.isnot(None),
            MessageAssets.status.in_([MessageAssetStatus.PENDING, MessageAssetStatus.RESUBMIT])
        )
        .distinct()
        .subquery()
    )
    pending_count = db.query(func.count()).select_from(pending_subquery).scalar() or 0

    # REJECTED のグループ数をカウント（ConversationMessages.group_byで）
    reject_subquery = (
        db.query(ConversationMessages.group_by)
        .select_from(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.group_by.isnot(None),
            MessageAssets.status == MessageAssetStatus.REJECTED
        )
        .distinct()
        .subquery()
    )
    reject_count = db.query(func.count()).select_from(reject_subquery).scalar() or 0

    # 予約送信（message status=PENDING）のグループ数をカウント
    # 審査中・拒否されたアセットを持つgroup_byを取得（別タブに表示されるため除外）
    group_by_with_pending_or_rejected_assets = (
        db.query(ConversationMessages.group_by)
        .join(MessageAssets, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.status == ConversationMessageStatus.PENDING,
            ConversationMessages.type == ConversationMessageType.BULK,
            ConversationMessages.deleted_at.is_(None),
            ConversationMessages.group_by.isnot(None),
            # 審査中・再申請中・拒否されたアセットを持つものを除外
            MessageAssets.status.in_([
                MessageAssetStatus.PENDING,
                MessageAssetStatus.RESUBMIT,
                MessageAssetStatus.REJECTED
            ])
        )
        .distinct()
        .subquery()
    )

    # 予約中のgroup_byを取得（審査中・拒否されたアセットを持つものを除外）
    reserved_subquery = (
        db.query(ConversationMessages.group_by)
        .filter(
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.status == ConversationMessageStatus.PENDING,
            ConversationMessages.type == ConversationMessageType.BULK,
            ConversationMessages.deleted_at.is_(None),
            ConversationMessages.group_by.isnot(None),
            # 審査中・拒否されたアセットを持つgroup_byを除外
            ~ConversationMessages.group_by.in_(
                db.query(group_by_with_pending_or_rejected_assets.c.group_by)
            )
        )
        .distinct()
        .subquery()
    )
    reserved_count = db.query(func.count()).select_from(reserved_subquery).scalar() or 0

    return {
        'pending_count': pending_count,
        'reject_count': reject_count,
        'reserved_count': reserved_count
    }


def get_reserved_bulk_messages(
    db: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 50
) -> List[dict]:
    """
    予約送信中の一斉送信メッセージを取得（group_byでグループ化、送信先数を含む）

    Args:
        db: データベースセッション
        user_id: ユーザーID
        skip: スキップ件数
        limit: 取得件数

    Returns:
        予約メッセージのリスト（グループ化済み、送信先数含む）
        各要素: {"message": ConversationMessages, "asset": MessageAssets | None, "recipient_count": int}
    """
    from sqlalchemy import func

    # Step 1: conversation_messages.group_byでグループ化して、各グループの代表メッセージと送信先数を取得
    # まず、group_byごとに最も古いメッセージIDを取得
    subquery = (
        db.query(
            ConversationMessages.id,
            func.row_number()
            .over(
                partition_by=ConversationMessages.group_by,
                order_by=ConversationMessages.created_at.asc()
            )
            .label("row_num")
        )
        .filter(
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.status == ConversationMessageStatus.PENDING,
            ConversationMessages.type == ConversationMessageType.BULK,
            ConversationMessages.deleted_at.is_(None),
            ConversationMessages.group_by.isnot(None)  # group_byがNULLでないもののみ
        )
        .subquery()
    )

    # 各グループの代表メッセージ（最初のメッセージ）のIDを取得
    representative_message_ids_query = (
        db.query(subquery.c.id)
        .filter(subquery.c.row_num == 1)
    )

    # 代表メッセージを取得
    # 審査中・拒否されたアセットを持つメッセージは除外（それらは別タブに表示）
    messages_with_pending_or_rejected_assets_subquery = (
        db.query(ConversationMessages.id)
        .join(MessageAssets, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.status == ConversationMessageStatus.PENDING,
            # 審査中・再申請中・拒否されたアセットを除外
            MessageAssets.status.in_([
                MessageAssetStatus.PENDING,
                MessageAssetStatus.RESUBMIT,
                MessageAssetStatus.REJECTED
            ])
        )
        .distinct()
        .subquery()
    )

    messages = (
        db.query(ConversationMessages)
        .filter(
            ConversationMessages.id.in_(representative_message_ids_query),
            # 審査中・拒否されたアセットを持つメッセージは除外
            ~ConversationMessages.id.in_(
                db.query(messages_with_pending_or_rejected_assets_subquery.c.id)
            )
        )
        .order_by(ConversationMessages.scheduled_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    if not messages:
        return []

    # group_byのリストを取得
    group_bys = [msg.group_by for msg in messages if msg.group_by]

    # 各group_byの送信先数をカウント
    recipient_counts = (
        db.query(
            ConversationMessages.group_by,
            func.count(ConversationMessages.id).label("count")
        )
        .filter(
            ConversationMessages.group_by.in_(group_bys),
            ConversationMessages.sender_user_id == user_id,
            ConversationMessages.status == ConversationMessageStatus.PENDING,
            ConversationMessages.type == ConversationMessageType.BULK,
            ConversationMessages.deleted_at.is_(None)
        )
        .group_by(ConversationMessages.group_by)
        .all()
    )

    # group_byをキーとした送信先数の辞書を作成
    recipient_count_dict = {group_by: count for group_by, count in recipient_counts}

    # メッセージIDを取得
    message_ids = [msg.id for msg in messages]

    # message_assetsを取得（LEFT JOIN）
    assets = (
        db.query(MessageAssets)
        .filter(
            MessageAssets.message_id.in_(message_ids),
            MessageAssets.status.notin_([MessageAssetStatus.PENDING, MessageAssetStatus.RESUBMIT])
        )
        .all()
    )

    # message_idをキーとした辞書を作成
    asset_dict = {}
    for asset in assets:
        if asset.message_id not in asset_dict:
            asset_dict[asset.message_id] = asset

    # メッセージとアセット、送信先数を結合
    result = []
    for message in messages:
        asset = asset_dict.get(message.id)
        recipient_count = recipient_count_dict.get(message.group_by, 1)

        result.append({
            "message": message,
            "asset": asset,  # assetがない場合はNone
            "recipient_count": recipient_count  # 送信先数
        })

    return result


def resubmit_message_asset_by_group_by_with_file(
    db: Session,
    group_by: str,
    user_id: UUID,
    new_storage_key: str,
    new_asset_type: int,
    message_text: Optional[str] = None
) -> Optional[MessageAssets]:
    """
    group_byで同じグループの全メッセージアセットを一括再申請/更新（ファイル更新を含む）
    - 拒否されたメッセージの再申請
    - 予約送信メッセージの更新（assetsがない場合も対応）

    Args:
        db: データベースセッション
        group_by: グループ化キー
        user_id: ユーザーID（権限チェック用）
        new_storage_key: 新しいS3ストレージキー
        new_asset_type: 新しいアセットタイプ（1=画像, 2=動画）
        message_text: メッセージ本文（オプション）

    Returns:
        更新された代表的なMessageAssetsオブジェクト or None
    """
    # group_byで同じグループの全アセットを取得（ConversationMessages.group_byでフィルタリング）
    assets = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            ConversationMessages.group_by == group_by,
            ConversationMessages.sender_user_id == user_id
        )
        .all()
    )

    # assetsが存在する場合は更新
    if assets:
        # 拒否されたメッセージの場合のみステータスチェック
        first_asset = assets[0]
        if first_asset.status == MessageAssetStatus.REJECTED:
            # 拒否されたメッセージの再申請
            for asset in assets:
                asset.storage_key = new_storage_key
                asset.asset_type = new_asset_type
                asset.status = MessageAssetStatus.RESUBMIT
                asset.reject_comments = None
        else:
            # 予約送信の更新など
            # 新しいファイルで更新
            for asset in assets:
                asset.storage_key = new_storage_key
                asset.asset_type = new_asset_type
    else:
        # assetsが存在しない場合（テキストのみ→画像追加）
        # group_byに紐づく全てのメッセージを取得して、新しいアセットを作成
        messages = (
            db.query(ConversationMessages)
            .filter(
                ConversationMessages.group_by == group_by,
                ConversationMessages.sender_user_id == user_id
            )
            .all()
        )

        # 各メッセージに対して新しいアセットを作成
        for message in messages:
            new_asset = MessageAssets(
                message_id=message.id,
                status=MessageAssetStatus.PENDING,  # 審査待ち
                asset_type=new_asset_type,
                storage_key=new_storage_key,
            )
            db.add(new_asset)

    # メッセージ本文も更新する場合（group_byの全メッセージを更新）
    if message_text is not None:
        messages = (
            db.query(ConversationMessages)
            .filter(
                ConversationMessages.group_by == group_by,
                ConversationMessages.sender_user_id == user_id
            )
            .all()
        )
        for message in messages:
            message.body_text = message_text

    db.commit()

    # 代表的なアセット1件を返す（最初に作成されたもの）
    representative_asset = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )

    if representative_asset:
        db.refresh(representative_asset)

    return representative_asset


def update_message_text_by_group_by(
    db: Session,
    group_by: str,
    user_id: UUID,
    message_text: Optional[str] = None
) -> Optional[MessageAssets]:
    """
    group_byで同じグループのメッセージ本文のみを更新（ファイル更新なし）

    Args:
        db: データベースセッション
        group_by: グループ化キー
        user_id: ユーザーID（権限チェック用）
        message_text: メッセージ本文（オプション）

    Returns:
        代表的なMessageAssetsオブジェクト or None（アセットが存在しない場合）
    """
    # メッセージ本文を更新する場合（group_byの全メッセージを更新）
    if message_text is not None:
        messages = (
            db.query(ConversationMessages)
            .filter(
                ConversationMessages.group_by == group_by,
                ConversationMessages.sender_user_id == user_id
            )
            .all()
        )
        for message in messages:
            message.body_text = message_text

    db.commit()

    # 代表的なアセット1件を返す（最初に作成されたもの）
    # アセットが存在しない場合はNoneを返す
    representative_asset = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )

    if representative_asset:
        db.refresh(representative_asset)

    return representative_asset


def resubmit_message_asset_by_group_by(
    db: Session,
    group_by: str,
    user_id: UUID,
    new_storage_key: Optional[str] = None,
    new_asset_type: Optional[int] = None,
    message_text: Optional[str] = None
) -> Optional[MessageAssets]:
    """
    group_byで同じグループの全メッセージアセットを一括再申請/更新
    - 拒否されたメッセージの再申請
    - 予約送信メッセージの更新（assetsがない場合も対応）

    Args:
        db: データベースセッション
        group_by: グループ化キー
        user_id: ユーザーID（権限チェック用）
        new_storage_key: 新しいS3ストレージキー（Noneの場合は画像削除）
        new_asset_type: 新しいアセットタイプ（1=画像, 2=動画、Noneの場合は画像削除）
        message_text: メッセージ本文（オプション）

    Returns:
        更新された代表的なMessageAssetsオブジェクト or None
    """
    # group_byで同じグループの全アセットを取得（ConversationMessages.group_byでフィルタリング）
    assets = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            ConversationMessages.group_by == group_by,
            ConversationMessages.sender_user_id == user_id
        )
        .all()
    )

    # assetsが存在する場合は更新
    if assets:
        # 拒否されたメッセージの場合のみステータスチェック
        first_asset = assets[0]
        if first_asset.status == MessageAssetStatus.REJECTED:
            # 拒否されたメッセージの再申請
            if new_storage_key is None or new_asset_type is None:
                # 再申請時は画像/動画必須
                return None

            for asset in assets:
                asset.storage_key = new_storage_key
                asset.asset_type = new_asset_type
                asset.status = MessageAssetStatus.RESUBMIT
                asset.reject_comments = None
        else:
            # 予約送信の更新など
            if new_storage_key is not None and new_asset_type is not None:
                # 新しいファイルで更新
                for asset in assets:
                    asset.storage_key = new_storage_key
                    asset.asset_type = new_asset_type
            elif new_storage_key is None and new_asset_type is None:
                # 画像削除（assetsを削除）
                for asset in assets:
                    db.delete(asset)
    else:
        # assetsが存在しない場合（テキストのみ→画像追加）
        if new_storage_key is not None and new_asset_type is not None:
            # group_byに紐づく全てのメッセージを取得して、新しいアセットを作成
            messages = (
                db.query(ConversationMessages)
                .filter(
                    ConversationMessages.group_by == group_by,
                    ConversationMessages.sender_user_id == user_id
                )
                .all()
            )

            # 各メッセージに対して新しいアセットを作成
            for message in messages:
                new_asset = MessageAssets(
                    message_id=message.id,
                    status=MessageAssetStatus.PENDING,  # 審査待ち
                    asset_type=new_asset_type,
                    storage_key=new_storage_key,
                )
                db.add(new_asset)

    # メッセージ本文も更新する場合（group_byの全メッセージを更新）
    if message_text is not None:
        messages = (
            db.query(ConversationMessages)
            .filter(
                ConversationMessages.group_by == group_by,
                ConversationMessages.sender_user_id == user_id
            )
            .all()
        )
        for message in messages:
            message.body_text = message_text

    db.commit()

    # 代表的なアセット1件を返す（最初に作成されたもの）
    # 削除された場合はNoneを返す
    representative_asset = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.group_by == group_by)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )

    if representative_asset:
        db.refresh(representative_asset)

    return representative_asset
