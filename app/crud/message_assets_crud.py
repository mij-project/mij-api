# app/crud/message_assets_crud.py
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional, List, Tuple
from datetime import datetime
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
    group_by: str = None,
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
        group_by=group_by,
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

    Args:
        db: データベースセッション
        group_by: グループ化キー

    Returns:
        更新された代表的なMessageAssetsオブジェクト or None
    """
    # 同じgroup_byを持つすべてのアセットを取得
    assets = (
        db.query(MessageAssets)
        .filter(MessageAssets.group_by == group_by)
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
        .filter(MessageAssets.group_by == group_by)
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

    Args:
        db: データベースセッション
        group_by: グループ化キー
        reject_comments: 拒否理由コメント

    Returns:
        更新された代表的なMessageAssetsオブジェクト or None
    """
    # 同じgroup_byを持つすべてのアセットを取得
    assets = (
        db.query(MessageAssets)
        .filter(MessageAssets.group_by == group_by)
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
        .filter(MessageAssets.group_by == group_by)
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
    
    # 総グループ数を取得
    count_query = (
        db.query(func.count(func.distinct(MessageAssets.group_by)))
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.sender_user_id == user_id)
    )
    
    if status is not None:
        count_query = count_query.filter(MessageAssets.status == status)
    
    # group_byでグループ化して、各グループの最初のアセットのcreated_atでソート
    subquery = (
        db.query(
            MessageAssets.group_by,
            func.min(MessageAssets.created_at).label("min_created_at")
        )
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.sender_user_id == user_id)
    )
    
    if status is not None:
        subquery = subquery.filter(MessageAssets.status == status)
    
    subquery = (
        subquery.group_by(MessageAssets.group_by)
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
                MessageAssets.group_by == group_by,
                MessageAssets.created_at == min_created_at,
                ConversationMessages.sender_user_id == user_id
            )
        )
        if status is not None:
            asset_query = asset_query.filter(MessageAssets.status == status)
        
        asset = asset_query.order_by(MessageAssets.created_at.asc()).first()
        if asset:
            assets.append(asset)
    
    asset_dict = {asset.group_by: asset for asset in assets}
    
    # メッセージIDのリストを取得
    message_ids = list(set([asset.message_id for asset in assets]))
    
    # メッセージ情報を一括取得
    messages = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id.in_(message_ids))
        .all()
    )
    message_dict = {msg.id: msg for msg in messages}
    
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
    
    # 総グループ数を取得
    count_query = db.query(func.count(func.distinct(MessageAssets.group_by)))
    if status is not None:
        count_query = count_query.filter(MessageAssets.status == status)
    total = count_query.scalar()
    
    # group_byでグループ化して、各グループの最初のアセットのcreated_atでソート
    # 各グループから代表的なアセット1件（最初に作成されたもの）を取得
    subquery = (
        db.query(
            MessageAssets.group_by,
            func.min(MessageAssets.created_at).label("min_created_at")
        )
    )
    
    if status is not None:
        subquery = subquery.filter(MessageAssets.status == status)
    
    subquery = (
        subquery.group_by(MessageAssets.group_by)
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
        asset_query = (
            db.query(MessageAssets)
            .filter(
                MessageAssets.group_by == group_by,
                MessageAssets.created_at == min_created_at
            )
        )
        if status is not None:
            asset_query = asset_query.filter(MessageAssets.status == status)
        
        asset = asset_query.order_by(MessageAssets.created_at.asc()).first()
        if asset:
            assets.append(asset)
    
    asset_dict = {asset.group_by: asset for asset in assets}
    
    # メッセージIDのリストを取得
    message_ids = list(set([asset.message_id for asset in assets]))
    
    # メッセージ情報を一括取得
    messages = (
        db.query(ConversationMessages)
        .filter(ConversationMessages.id.in_(message_ids))
        .all()
    )
    message_dict = {msg.id: msg for msg in messages}
    
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

    Args:
        db: データベースセッション
        group_by: グループ化キー
        user_id: ユーザーID（送信者の確認用）

    Returns:
        詳細情報の辞書 or None
    """
    # group_byでグループ化されたアセットから代表的な1件を取得（最初に作成されたもの）
    asset = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            MessageAssets.group_by == group_by,
            ConversationMessages.sender_user_id == user_id
        )
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

    # 詳細情報を辞書形式で返却
    return {
        "asset": asset,
        "message": message,
        "conversation": conversation,
    }


def get_message_asset_detail_by_group_by_for_admin(
    db: Session, group_by: str
) -> Optional[dict]:
    """
    管理者用：group_byでメッセージアセット詳細を取得（送信者・受信者・メッセージ情報含む）

    Args:
        db: データベースセッション
        group_by: グループ化キー

    Returns:
        詳細情報の辞書 or None
    """
    # group_byでグループ化されたアセットから代表的な1件を取得（最初に作成されたもの）
    asset = (
        db.query(MessageAssets)
        .filter(MessageAssets.group_by == group_by)
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
        {'pending_count': int, 'reject_count': int}
    """
    from sqlalchemy import func

    # PENDING と RESUBMIT のグループ数をカウント
    pending_subquery = (
        db.query(MessageAssets.group_by)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.sender_user_id == user_id)
        .filter(MessageAssets.status.in_([MessageAssetStatus.PENDING, MessageAssetStatus.RESUBMIT]))
        .distinct()
        .subquery()
    )
    pending_count = db.query(func.count()).select_from(pending_subquery).scalar() or 0

    # REJECTED のグループ数をカウント
    reject_subquery = (
        db.query(MessageAssets.group_by)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(ConversationMessages.sender_user_id == user_id)
        .filter(MessageAssets.status == MessageAssetStatus.REJECTED)
        .distinct()
        .subquery()
    )
    reject_count = db.query(func.count()).select_from(reject_subquery).scalar() or 0

    return {
        'pending_count': pending_count,
        'reject_count': reject_count
    }


def resubmit_message_asset_by_group_by(
    db: Session,
    group_by: str,
    user_id: UUID,
    new_storage_key: str,
    new_asset_type: int,
    message_text: Optional[str] = None
) -> Optional[MessageAssets]:
    """
    group_byで同じグループの全メッセージアセットを一括再申請

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
    # group_byで同じグループの全アセットを取得
    assets = (
        db.query(MessageAssets)
        .join(ConversationMessages, MessageAssets.message_id == ConversationMessages.id)
        .filter(
            MessageAssets.group_by == group_by,
            ConversationMessages.sender_user_id == user_id
        )
        .all()
    )

    if not assets:
        return None

    # 最初のアセットのステータスをチェック（全て同じステータスのはず）
    if assets[0].status != MessageAssetStatus.REJECTED:
        return None

    # 同じgroup_byの全アセットを一括更新
    for asset in assets:
        asset.storage_key = new_storage_key
        asset.asset_type = new_asset_type
        asset.status = MessageAssetStatus.RESUBMIT
        asset.reject_comments = None

    # メッセージ本文も更新する場合（全メッセージを更新）
    if message_text is not None:
        message_ids = [asset.message_id for asset in assets]
        messages = (
            db.query(ConversationMessages)
            .filter(ConversationMessages.id.in_(message_ids))
            .all()
        )
        for message in messages:
            message.body_text = message_text

    db.commit()

    # 代表的なアセット1件を返す（最初に作成されたもの）
    representative_asset = (
        db.query(MessageAssets)
        .filter(MessageAssets.group_by == group_by)
        .order_by(MessageAssets.created_at.asc())
        .first()
    )

    if representative_asset:
        db.refresh(representative_asset)

    return representative_asset
