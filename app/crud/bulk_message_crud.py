# app/crud/bulk_message_crud.py
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from uuid import UUID
import uuid
from typing import List, Dict, Optional
from datetime import datetime
from sqlalchemy.types import String
from app.constants.enums import ConversationMessageStatus
from app.models.payments import Payments
from app.models.subscriptions import Subscriptions
from app.models.plans import Plans
from app.models.social import Follows
from app.constants.enums import (
    PaymentType,
    PaymentStatus,
    SubscriptionStatus,
    SubscriptionType,
    ItemType,
    MessageAssetStatus,
)
from app.crud import conversations_crud, message_assets_crud
from app.core.logger import Logger
logger = Logger.get_logger()

def get_bulk_message_recipients(db: Session, creator_user_id: UUID) -> Dict:
    """
    一斉送信の送信先リスト情報を取得

    Args:
        db: データベースセッション
        creator_user_id: クリエイターのユーザーID

    Returns:
        {
            'chip_senders_count': int,
            'single_purchasers_count': int,
            'plan_subscribers': [{'plan_id': UUID, 'plan_name': str, 'subscribers_count': int}]
        }
    """
    # 1. チップを送ってくれたユーザー数（重複なし）
    chip_senders_count = (
        db.query(func.count(distinct(Payments.buyer_user_id)))
        .filter(
            Payments.seller_user_id == creator_user_id,
            Payments.payment_type == PaymentType.CHIP,
            Payments.status == PaymentStatus.SUCCEEDED
        )
        .scalar() or 0
    )

    # 2. 単品販売購入ユーザー数（重複なし）
    # subscriptions テーブルで order_type = SubscriptionType.SINGLE のユーザーを取得
    single_purchasers_count = (
        db.query(func.count(distinct(Subscriptions.user_id)))
        .filter(
            Subscriptions.creator_id == creator_user_id,
            Subscriptions.order_type == SubscriptionType.SINGLE,
            Subscriptions.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED])
        )
        .scalar() or 0
    )

    # 3 フォロワーユーザー数（重複なし）
    follower_users_count = (
        db.query(func.count(distinct(Follows.follower_user_id)))
        .filter(
            Follows.creator_user_id == creator_user_id
        )
        .scalar() or 0
    )

    # 3. プラン別加入者情報
    # subscriptions テーブルで order_type = ItemType.PLAN のユーザーを集計
    # order_id を文字列として plans テーブルと結合
    plan_subscribers = (
        db.query(
            Plans.id.label('plan_id'),
            Plans.name.label('plan_name'),
            func.count(Subscriptions.id).label('subscribers_count')
        )
        .join(Plans, Subscriptions.order_id == func.cast(Plans.id, String))
        .filter(
            Subscriptions.creator_id == creator_user_id,
            Subscriptions.order_type == ItemType.PLAN,
            Subscriptions.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED])
        )
        .group_by(Plans.id, Plans.name)
        .all()
    )

    plan_subscribers_list = [
        {
            'plan_id': str(row.plan_id),
            'plan_name': row.plan_name,
            'subscribers_count': row.subscribers_count
        }
        for row in plan_subscribers
    ]

    return {
        'chip_senders_count': chip_senders_count,
        'single_purchasers_count': single_purchasers_count,
        'plan_subscribers': plan_subscribers_list,
        'follower_users_count': follower_users_count
    }


def get_target_user_ids(
    db: Session,
    creator_user_id: UUID,
    send_to_chip_senders: bool,
    send_to_single_purchasers: bool,
    send_to_follower_users: bool,
    send_to_plan_subscribers: List[UUID]
) -> List[UUID]:
    """
    一斉送信の対象ユーザーIDリストを取得（重複なし）

    Args:
        db: データベースセッション
        creator_user_id: クリエイターのユーザーID
        send_to_chip_senders: チップ送信者に送るか
        send_to_single_purchasers: 単品購入者に送るか
        send_to_follower_users: フォロワーユーザーに送るか
        send_to_plan_subscribers: 送信対象プランIDリスト

    Returns:
        対象ユーザーIDのリスト
    """
    target_user_ids = set()

    # 1. チップを送ってくれたユーザー
    if send_to_chip_senders:
        chip_senders = (
            db.query(distinct(Payments.buyer_user_id))
            .filter(
                Payments.seller_user_id == creator_user_id,
                Payments.payment_type == PaymentType.CHIP,
                Payments.status == PaymentStatus.SUCCEEDED
            )
            .all()
        )
        target_user_ids.update([row[0] for row in chip_senders])

    # 2. 単品販売購入ユーザー
    if send_to_single_purchasers:
        single_purchasers = (
            db.query(distinct(Subscriptions.user_id))
            .filter(
                Subscriptions.creator_id == creator_user_id,
                Subscriptions.order_type == SubscriptionType.SINGLE,
                Subscriptions.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED])
            )
            .all()
        )
        target_user_ids.update([row[0] for row in single_purchasers])

    # 3. フォロワーユーザー
    if send_to_follower_users:
        follower_users = (
            db.query(distinct(Follows.follower_user_id))
            .filter(
                Follows.creator_user_id == creator_user_id
            )
            .all()
        )
        target_user_ids.update([row[0] for row in follower_users])

    # 4. プラン加入者
    if send_to_plan_subscribers:
        # プランIDリストを文字列に変換
        plan_id_strings = [str(plan_id) for plan_id in send_to_plan_subscribers]

        plan_subscribers = (
            db.query(distinct(Subscriptions.user_id))
            .filter(
                Subscriptions.creator_id == creator_user_id,
                Subscriptions.order_type == ItemType.PLAN,
                Subscriptions.order_id.in_(plan_id_strings),
                Subscriptions.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED])
            )
            .all()
        )
        target_user_ids.update([row[0] for row in plan_subscribers])

    return list(target_user_ids)


def send_bulk_messages(
    db: Session,
    creator_user_id: UUID,
    message_text: str,
    target_user_ids: List[UUID],
    asset_storage_key: Optional[str] = None,
    asset_type: Optional[int] = None,
    scheduled_at: Optional[datetime] = None
) -> int:
    """
    対象ユーザーに一斉メッセージを送信

    Args:
        db: データベースセッション
        creator_user_id: クリエイターのユーザーID
        message_text: メッセージ本文
        target_user_ids: 送信対象ユーザーIDリスト
        asset_storage_key: アセットのストレージキー（任意）
        asset_type: アセットタイプ（任意）
        scheduled_at: 予約送信日時（任意）
    Returns:
        送信数
    """
    sent_count = 0
    group_by = str(uuid.uuid4())
    message_ids = []
    for user_id in target_user_ids:
        # 会話を取得または作成（type=2のDM）
        conversation = conversations_crud.get_or_create_dm_conversation(
            db=db,
            user_id_1=creator_user_id,
            user_id_2=user_id
        )

        # メッセージを作成
        if scheduled_at:
            message = conversations_crud.create_bulk_message(
                db=db,
                conversation_id=conversation.id,
                sender_user_id=creator_user_id,
                body_text=message_text,
                status=ConversationMessageStatus.PENDING,
                scheduled_at=scheduled_at,
                group_by=group_by
            )
            message_ids.append(message.id)
        else:
            message = conversations_crud.create_bulk_message(
                db=db,
                conversation_id=conversation.id,
                sender_user_id=creator_user_id,
                body_text=message_text,
                status=ConversationMessageStatus.ACTIVE,
                group_by=group_by
            )


        # アセットがある場合はmessage_assetレコードを作成
        if asset_storage_key and asset_type:
            message_assets_crud.create_message_asset(
                db=db,
                message_id=message.id,
                asset_type=asset_type,
                storage_key=asset_storage_key,
                status=MessageAssetStatus.PENDING,
            )

        sent_count += 1

    return sent_count, message_ids, group_by