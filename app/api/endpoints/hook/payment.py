"""
CREDIX決済Webhookエンドポイント
"""

import math
from fastapi import APIRouter, Query, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from typing import Optional, Tuple
from uuid import UUID
from datetime import datetime, timedelta, timezone
from app.crud.user_settings_curd import get_user_settings_by_user_id
from app.schemas.notification import NotificationType
from app.schemas.user_settings import UserSettingsType
from app.core.logger import Logger
from app.db.base import get_db
from app.crud import (
    payment_transactions_crud,
    user_providers_crud,
    payments_crud,
    subscriptions_crud,
    price_crud,
    plan_crud,
    user_crud,
    notifications_crud,
    conversations_crud,
    profile_crud,
)
from app.constants.enums import (
    PaymentTransactionStatus,
    PaymentTransactionType,
    PaymentStatus,
    SubscriptionType,
    SubscriptionStatus,
    TransactionType,
    ItemType,
    # ConversationType,
    # ParticipantType,
    PaymentType,
    ConversationMessageStatus,
)
from app.services.email.send_email import (
    send_payment_succuces_email,
    send_payment_faild_email,
    send_selling_info_email,
    send_cancel_subscription_email,
    send_buyer_cancel_subscription_email,
    send_chip_payment_buyer_success_email,
    send_chip_payment_seller_success_email,
)
from app.models.payment_transactions import PaymentTransactions
from app.models.payments import Payments
from app.models.subscriptions import Subscriptions
# from app.models.conversations import Conversations
# from app.models.conversation_participants import ConversationParticipants
from app.models.conversation_messages import ConversationMessages
# from datetime import datetime, timezone
import os

CDN_BASE_URL = os.environ.get("CDN_BASE_URL")

logger = Logger.get_logger()
router = APIRouter()

FREE_ORDER_ID = "FREE_ORDER"

# CREDIXへのレスポンス
CREDIX_SUCCESS_RESPONSE = "successok"
CREDIX_ERROR_RESPONSE = "error"
SUBSCRIPTION_DURATION_DAYS = 30
RESULT_OK = "ok"
RESULT_NG = "ng"


def _log_webhook_received(
    clientip: Optional[str],
    telno: Optional[str],
    email: Optional[str],
    sendid: Optional[str],
    sendpoint: Optional[str],
    result: Optional[str],
    money: Optional[int],
    cardbrand: Optional[str],
    cardnumber: Optional[str],
    yuko: Optional[str],
) -> None:
    """Webhook受信ログを出力"""
    logger.info("=== CREDIX Webhook受信 ===")
    logger.info(f"clientip: {clientip}")
    logger.info(f"telno: {telno}")
    logger.info(f"email: {email}")
    logger.info(f"sendid: {sendid}")
    logger.info(f"sendpoint: {sendpoint}")
    logger.info(f"result: {result}")
    logger.info(f"money: {money}")
    logger.info(f"cardbrand: {cardbrand}")
    logger.info(f"cardnumber: {cardnumber}")
    logger.info(f"yuko: {yuko}")


def _get_order_info(
    db: Session,
    transaction: PaymentTransactions,
) -> Tuple[int, UUID, int]:
    """
    注文情報（価格、売主ユーザーID、プラットフォーム手数料率）を取得

    Args:
        db: データベースセッション
        transaction: 決済トランザクション

    Returns:
        (payment_price, seller_user_id, platform_fee_percent) のタプル

    Raises:
        ValueError: 注文情報が見つからない場合
    """
    if transaction.type == PaymentTransactionType.SINGLE:
        price, post, creator = price_crud.get_price_and_post_by_id(
            db, transaction.order_id
        )
        if not price or not post or not creator:
            raise ValueError(f"Price or post not found: {transaction.order_id}")
        return price.price, post.creator_user_id, creator.platform_fee_percent
    else:  # SUBSCRIPTION
        plan, creator = plan_crud.get_plan_and_creator_by_id(db, transaction.order_id)
        if not plan or not creator:
            raise ValueError(f"Plan not found: {transaction.order_id}")
        return plan.price, plan.creator_user_id, creator.platform_fee_percent


def _get_payment_info(
    db: Session,
    transaction: PaymentTransactions,
) -> Tuple[str, str]:
    """
    決済情報を取得（通知用の相対URLとコンテンツ名）

    Args:
        db: データベースセッション
        transaction: 決済トランザクション

    Returns:
        (content_url, contents_name) のタプル

    Raises:
        ValueError: 注文情報が見つからない場合
    """
    if transaction.type == PaymentTransactionType.SINGLE:
        price, post, creator = price_crud.get_price_and_post_by_id(
            db, transaction.order_id
        )
        if not price or not post:
            raise ValueError(f"Price or post not found: {transaction.order_id}")
        contents_name = post.description
        content_url = f"/post/detail?post_id={post.id}"
    else:  # SUBSCRIPTION
        plan = plan_crud.get_plan_by_id(db, transaction.order_id)
        if not plan:
            raise ValueError(f"Plan not found: {transaction.order_id}")
        contents_name = plan.name
        content_url = f"/plan/{plan.id}"

    return content_url, contents_name


def _get_selling_info(
    db: Session,
    transaction: PaymentTransactions,
) -> Tuple[str, str, str, UUID, str, int]:
    """
    売り上げ情報を取得

    Args:
        db: データベースセッション
        transaction: 決済トランザクション

    Returns:
        (content_url, contents_name, seller_name, seller_user_id, seller_email, contents_type) のタプル

    Raises:
        ValueError: 注文情報が見つからない場合
    """
    if transaction.type == PaymentTransactionType.SINGLE:
        price, post, creator = price_crud.get_price_and_post_by_id(
            db, transaction.order_id
        )
        if not price or not post:
            raise ValueError(f"Price or post not found: {transaction.order_id}")
        seller_user_id = post.creator_user_id
        contents_name = post.description
        content_url = f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/post/detail?post_id={post.id}"
        contents_type = PaymentTransactionType.SINGLE
    else:  # SUBSCRIPTION
        plan = plan_crud.get_plan_by_id(db, transaction.order_id)
        if not plan:
            raise ValueError(f"Plan not found: {transaction.order_id}")
        seller_user_id = plan.creator_user_id
        contents_name = plan.name
        content_url = (
            f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/plan/{plan.id}"
        )
        contents_type = PaymentTransactionType.SUBSCRIPTION

    seller_user = user_crud.get_user_by_id(db, seller_user_id)
    if not seller_user:
        raise ValueError(f"Seller user not found: {seller_user_id}")

    seller_name = seller_user.profile_name
    seller_email = seller_user.email

    return (
        content_url,
        contents_name,
        seller_name,
        seller_user_id,
        seller_email,
        contents_type,
    )


def _create_payment_record(
    db: Session,
    transaction: PaymentTransactions,
    payment_price: int,
    seller_user_id: UUID,
    payment_amount: int,
    platform_fee: int,
    status: int,
) -> Payments:
    """
    決済レコードを作成

    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        payment_price: 商品価格
        seller_user_id: 売主ユーザーID
        payment_amount: 決済金額
        platform_fee: プラットフォーム手数料（金額）
        status: 決済ステータス（PaymentStatus）

    Returns:
        作成された決済レコード
    """
    return payments_crud.create_payment(
        db=db,
        transaction_id=transaction.id,
        payment_type=transaction.type,
        order_id=transaction.order_id,
        order_type=transaction.type,
        provider_id=transaction.provider_id,
        provider_payment_id=transaction.session_id,
        buyer_user_id=transaction.user_id,
        seller_user_id=seller_user_id,
        payment_amount=payment_amount,
        payment_price=payment_price,
        status=status,
        platform_fee=platform_fee,
    )


def _create_subscription_record(
    db: Session,
    transaction: PaymentTransactions,
    seller_user_id: UUID,
    payment_id: UUID,
) -> Subscriptions:
    """
    サブスクリプションレコードを作成

    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        seller_user_id: 売主ユーザーID
        payment_id: 決済ID

    Returns:
        作成されたサブスクリプションレコード
    """
    # トランザクションタイプに応じてサブスクリプションタイプを決定
    # PaymentTransactionType.SUBSCRIPTION(2) -> SubscriptionType.PLAN(1)
    # PaymentTransactionType.SINGLE(1) -> SubscriptionType.SINGLE(2)
    access_type = (
        SubscriptionType.PLAN
        if transaction.type == PaymentTransactionType.SUBSCRIPTION
        else SubscriptionType.SINGLE
    )

    # order_typeはItemTypeを使用
    # PaymentTransactionType.SUBSCRIPTION(2) -> ItemType.PLAN(2) ※プランID
    # PaymentTransactionType.SINGLE(1) -> ItemType.POST(1) ※投稿ID (price_idではなく)
    # 注意: 単品購入の場合、order_idにはprice_idが入るため、order_typeはItemType.POST(1)とする
    order_type = (
        ItemType.PLAN
        if transaction.type == PaymentTransactionType.SUBSCRIPTION
        else ItemType.POST
    )

    access_start = datetime.now(timezone.utc)
    access_end = (
        access_start + timedelta(days=SUBSCRIPTION_DURATION_DAYS)
        if access_type == SubscriptionType.PLAN
        else None
    )
    next_billing_date = access_end if access_type == SubscriptionType.PLAN else None

    return subscriptions_crud.create_subscription(
        db=db,
        access_type=access_type,
        user_id=transaction.user_id,
        creator_id=seller_user_id,
        order_id=transaction.order_id,
        order_type=order_type,
        access_start=access_start,
        access_end=access_end,
        next_billing_date=next_billing_date,
        provider_id=transaction.provider_id,
        payment_id=payment_id,
        status=SubscriptionStatus.ACTIVE,
    )


def _update_or_create_user_provider(
    db: Session,
    transaction: PaymentTransactions,
    send_id: Optional[str],
    cardbrand: Optional[str],
    cardnumber: Optional[str],
    yuko: Optional[str],
    main_card: bool,
) -> None:
    """
    ユーザープロバイダー情報を更新または作成

    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        send_id: CREDIXのsendid
        cardbrand: カードブランド
        cardnumber: カード番号
        yuko: 有効期限
        main_card: メインカードかどうか
    """
    if not send_id:
        return

    user_provider = user_providers_crud.get_user_provider_by_sendid(db, send_id)
    if not user_provider:
        user_provider = user_providers_crud.create_user_provider(
            db=db,
            user_id=transaction.user_id,
            provider_id=transaction.provider_id,
            sendid=send_id,
            cardbrand=cardbrand,
            cardnumber=cardnumber,
            yuko=yuko,
            main_card=main_card,
        )
        logger.info(
            f"Created user_provider: user_id={transaction.user_id}, sendid={send_id}"
        )
    else:
        user_providers_crud.update_last_used_at(
            db=db, user_provider_id=user_provider.id
        )
        logger.info(f"Updated user_provider last_used_at: {user_provider.id}")


def _handle_successful_payment(
    db: Session,
    transaction: PaymentTransactions,
    payment_amount: int,
    send_id: Optional[str],
    email: Optional[str],
    cardbrand: Optional[str],
    cardnumber: Optional[str],
    yuko: Optional[str],
    transaction_origin: Optional[str],
) -> None:
    """
    決済成功時の処理

    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        payment_amount: 決済金額
        send_id: CREDIXのsendid
        cardbrand: カードブランド
        cardnumber: カード番号
        yuko: 有効期限
        transaction_origin: トランザクションオリジン
    """
    logger.info(f"決済成功: transaction_id={transaction.id}")

    # トランザクションステータスを完了に更新
    payment_transactions_crud.update_transaction_status(
        db=db,
        transaction_id=transaction.id,
        status=PaymentTransactionStatus.COMPLETED,
    )

    if transaction_origin == TransactionType.PAYMENT_ORIGIN_FREE:
        # 0円決済（無料）の決済レコードを作成
        payment = _create_payment_record(
            db=db,
            transaction=transaction,
            payment_price=0,
            seller_user_id=transaction.user_id,
            platform_fee=0,
            payment_amount=0,
            status=PaymentStatus.SUCCEEDED,
        )
        logger.info(f"Free payment created: {payment.id}")

    else:
        # 注文情報を取得
        try:
            payment_price, seller_user_id, platform_fee = _get_order_info(
                db, transaction
            )
        except ValueError as e:
            logger.error(str(e))
            raise

        payment_price_from_credix = (payment_amount * 100 + 110 - 1) // 110
        # 決済レコードを作成
        payment = _create_payment_record(
            db=db,
            transaction=transaction,
            payment_price=payment_price_from_credix,
            seller_user_id=seller_user_id,
            platform_fee=platform_fee,
            payment_amount=payment_amount,
            status=PaymentStatus.SUCCEEDED,
        )

        # サブスクリプションレコードを作成
        subscription = _create_subscription_record(
            db=db,
            transaction=transaction,
            seller_user_id=seller_user_id,
            payment_id=payment.id,
        )

        logger.info(f"Payment created: {payment.id}")
        logger.info(f"Subscription created: {subscription.id}")

    # ユーザープロバイダー情報を更新または作成
    main_card = (
        True if transaction_origin == TransactionType.PAYMENT_ORIGIN_FREE else False
    )
    _update_or_create_user_provider(
        db, transaction, send_id, cardbrand, cardnumber, yuko, main_card
    )
    return payment


def _expire_existing_subscriptions(
    db: Session,
    order_id: str,
) -> None:
    """
    既存のアクティブなサブスクリプションを期限切れにする

    Args:
        db: データベースセッション
        order_id: 注文ID
    """
    subscriptions = subscriptions_crud.get_subscription_by_order_id(db, order_id)
    if not subscriptions:
        return

    for subscription in subscriptions:
        subscriptions_crud.update_subscription_status(
            db, subscription.id, SubscriptionStatus.EXPIRED
        )
        logger.info(f"Expired subscription updated: subscription_id={subscription.id}")


def _handle_failed_payment(
    db: Session,
    transaction: PaymentTransactions,
    payment_amount: int,
    transaction_origin: Optional[str],
) -> None:
    """
    決済失敗時の処理

    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        payment_amount: 決済金額
        transaction_origin: トランザクションオリジン
    """
    logger.info(f"決済失敗: transaction_id={transaction.id}")

    # トランザクションステータスを失敗に更新
    payment_transactions_crud.update_transaction_status(
        db=db,
        transaction_id=transaction.id,
        status=PaymentTransactionStatus.FAILED,
    )

    # 注文情報を取得
    try:
        payment_price, seller_user_id, platform_fee = _get_order_info(db, transaction)
    except ValueError as e:
        logger.error(f"Failed to get order info: {e}")
        raise
    payment_price_from_credix = (payment_amount * 100 + 110 - 1) // 110
    # 決済レコードを作成
    payment = _create_payment_record(
        db=db,
        transaction=transaction,
        payment_price=payment_price_from_credix,
        seller_user_id=seller_user_id,
        platform_fee=platform_fee,
        payment_amount=payment_amount,
        status=PaymentStatus.FAILED,
    )

    # バッチ決済失敗時でサブスクリプションタイプの場合、期限切れサブスクリプションを処理
    if (
        transaction_origin == TransactionType.PAYMENT_ORIGIN_BATCH
        and transaction.type == PaymentTransactionType.SUBSCRIPTION
    ):
        # 既存のアクティブなサブスクリプションを期限切れにする
        _expire_existing_subscriptions(db, transaction.order_id)

        # 期限切れサブスクリプションレコードを作成
        subscriptions_crud.create_expired_subscription(
            db=db,
            user_id=transaction.user_id,
            creator_id=seller_user_id,
            order_id=transaction.order_id,
            order_type=transaction.type,
        )
        logger.info(
            f"Expired subscription created for batch failed payment: transaction_id={transaction.id}"
        )
    return payment


def _send_payment_notifications_for_buyer(
    db: Session,
    result: str,
    send_id: Optional[str],
    email: Optional[str],
    money: Optional[int],
    transaction: PaymentTransactions,
    transaction_origin: Optional[str],
) -> None:
    """
    決済成功・失敗時のメール送信と通知追加
    """

    # バッチからの成功時は通知を送らない
    if (
        transaction_origin == TransactionType.PAYMENT_ORIGIN_BATCH
        and result == RESULT_OK
    ):
        return

    # バッチからの失敗時、またはフロントエンドからのリクエスト時のみ処理を続行
    is_batch_failure = (
        transaction_origin == TransactionType.PAYMENT_ORIGIN_BATCH
        and result == RESULT_NG
    )
    is_frontend_request = transaction_origin == TransactionType.PAYMENT_ORIGIN_FRONT

    if not (is_batch_failure or is_frontend_request):
        return

    # 購入者ユーザー情報を取得
    buyer_user = user_crud.get_user_by_id(db, transaction.user_id)
    user_name = buyer_user.profile_name
    purchase_history_url = (
        f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/bought/post"
    )
    sendid = send_id
    transaction_id = transaction.id
    # UTCからJSTに変換
    jst = timezone(timedelta(hours=9))
    if transaction.updated_at.tzinfo is None:
        # naive datetimeの場合はUTCとして扱う
        utc_time = transaction.updated_at.replace(tzinfo=timezone.utc)
    else:
        utc_time = transaction.updated_at
    jst_time = utc_time.astimezone(jst)
    payment_date = jst_time.strftime("%Y-%m-%d %H:%M:%S")
    amount = money
    user_email = email

    # 通知用URLとコンテンツ名を取得（相対パス）
    notification_redirect_url, contents_name = _get_payment_info(db, transaction)

    # メール用URLを生成（完全なURL）
    frontend_url = os.environ.get("FRONTEND_URL", "https://mijfans.jp")
    email_content_url = f"{frontend_url}{notification_redirect_url}"

    # トランザクションタイプを確認（プラン解約の通知が必要かどうか）
    is_subscription = transaction.type == PaymentTransactionType.SUBSCRIPTION
    is_payment_failed = result == RESULT_NG

    # 通知内容を作成
    if is_payment_failed and is_subscription:
        # プラン解約の通知
        title = f"{contents_name}プランの決済に失敗したため、プランが解約されました"
        subtitle = f"{contents_name}プランの決済に失敗したため、プランが解約されました"
    else:
        title = "決済が完了しました" if result == RESULT_OK else "決済に失敗しました"
        subtitle = "決済が完了しました" if result == RESULT_OK else "決済に失敗しました"

    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
        "redirect_url": notification_redirect_url,
    }

    try:
        if result == RESULT_OK:
            send_payment_succuces_email(
                to=user_email,
                content_url=email_content_url,
                transaction_id=transaction_id,
                contents_name=contents_name,
                payment_date=payment_date,
                amount=amount,
                sendid=sendid,
                user_name=user_name,
                user_email=user_email,
                purchase_history_url=purchase_history_url,
            )
        else:
            if is_subscription:
                # プラン解約のメールを送信
                # クリエイター情報を取得
                plan = plan_crud.get_plan_by_id(db, transaction.order_id)
                if plan:
                    creator_user = user_crud.get_user_by_id(db, plan.creator_user_id)
                    creator_user_name = (
                        creator_user.profile_name if creator_user else None
                    )
                    send_buyer_cancel_subscription_email(
                        to=user_email,
                        user_name=user_name,
                        creator_user_name=creator_user_name,
                        plan_name=contents_name,
                        plan_url=email_content_url,
                    )
                else:
                    # プラン情報が取得できない場合は通常の決済失敗メールを送信
                    send_payment_faild_email(
                        to=user_email,
                        transaction_id=transaction_id,
                        failure_date=payment_date,
                        sendid=sendid,
                        user_name=user_name,
                        user_email=user_email,
                    )
            else:
                send_payment_faild_email(
                    to=user_email,
                    transaction_id=transaction_id,
                    failure_date=payment_date,
                    sendid=sendid,
                    user_name=user_name,
                    user_email=user_email,
                )

    except Exception as e:
        logger.error(f"Failed to send payment email: {e}")
        return

    # 通知を追加（購入者向け - NotificationType.USERS）
    if is_payment_failed and is_subscription:
        # プラン解約の通知
        notifications_crud.add_notification_for_cancel_subscription(
            db=db,
            notification={
                "user_id": buyer_user.id,
                "type": NotificationType.USERS,
                "payload": payload,
            },
        )
    else:
        # 通常の決済通知
        notifications_crud.add_notification_for_payment_succuces(
            db=db,
            notification={
                "user_id": buyer_user.id,
                "type": NotificationType.USERS,
                "payload": payload,
            },
        )


def _add_payment_notifications_for_seller(
    db: Session,
    transaction: PaymentTransactions,
    result: str,
    transaction_origin: Optional[str],
) -> None:
    """販売者への決済通知を追加"""

    # バッチからのリクエストで失敗の場合、またはフロントエンドからのリクエストで成功の場合のみ処理を続行
    # それ以外の場合は通知を追加しない
    is_batch_failure = (
        result == RESULT_NG
        and transaction_origin == TransactionType.PAYMENT_ORIGIN_BATCH
    )
    is_batch_success = (
        result == RESULT_OK
        and transaction_origin == TransactionType.PAYMENT_ORIGIN_BATCH
    )
    is_frontend_success = (
        result == RESULT_OK
        and transaction_origin == TransactionType.PAYMENT_ORIGIN_FRONT
    )

    if not (is_batch_failure or is_frontend_success or is_batch_success):
        return

    buyer_user = user_crud.get_user_by_id(db, transaction.user_id)
    buyer_name = buyer_user.profile_name

    # 通知用は相対パス
    notification_redirect_url = "/account/sale"

    # メール用は完全なURL
    dashboard_url = (
        f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/account/sale"
    )

    (
        content_url,
        contents_name,
        seller_name,
        seller_user_id,
        seller_email,
        contents_type,
    ) = _get_selling_info(db, transaction)

    # バッチからの失敗時のメッセージ
    if is_batch_failure:
        title = f"{buyer_name}さんが{contents_name}プランの決済に失敗したため、プラン解約しました"
        subtitle = f"{buyer_name}さんが{contents_name}プランの決済に失敗したため、プラン解約しました"
    # フロントエンドからの成功時のメッセージ
    elif is_frontend_success:
        if contents_type == PaymentTransactionType.SINGLE:
            title = f"{buyer_name}さんが{contents_name}を購入しました"
            subtitle = f"{buyer_name}さんが{contents_name}を購入しました"
        else:
            title = f"{buyer_name}さんが{contents_name}プランに加入しました"
            subtitle = f"{buyer_name}さんが{contents_name}プランに加入しました"
    elif is_batch_success:
        title = f"{buyer_name}さんが{contents_name}プランを続き加入しました"
        subtitle = f"{buyer_name}さんが{contents_name}プランを続き加入しました"
    # アバターURLの取得（buyer_userのprofileが存在するか確認）
    avatar_url = "https://logo.mijfans.jp/bimi/logo.svg"

    if hasattr(buyer_user, "profile") and buyer_user.profile:
        if buyer_user.profile.avatar_url:
            # S3の相対パスの場合、完全なURLに変換
            avatar_path = buyer_user.profile.avatar_url
            avatar_url = f"{CDN_BASE_URL}/{avatar_path}"
    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": avatar_url,
        "redirect_url": notification_redirect_url,
    }

    # TODO: ユーザー設定をチェックして送信する
    send_flg = True

    if send_flg:
        try:
            if is_batch_failure:
                send_cancel_subscription_email(
                    to=seller_email,
                    user_name=buyer_name,
                    creator_user_name=seller_name,
                    plan_name=contents_name,
                    plan_url=content_url,
                )
            elif is_frontend_success or is_batch_success:
                send_selling_info_email(
                    to=seller_email,
                    buyer_name=buyer_name,
                    contents_name=contents_name,
                    seller_name=seller_name,
                    content_url=content_url,
                    contents_type=contents_type,
                    dashboard_url=dashboard_url,
                )
        except Exception as e:
            logger.error(f"Failed to send selling info email: {e}")
            return

    # 通知を追加（販売者向け - NotificationType.PAYMENTS）
    notification = {
        "user_id": seller_user_id,
        "type": NotificationType.PAYMENTS,
        "payload": payload,
    }
    notifications_crud.add_notification_for_selling_info(
        db=db, notification=notification
    )


def _send_chip_payment_notifications_for_buyer(
    db: Session,
    transaction: PaymentTransactions,
    result: str,
    email: Optional[str],
    money: Optional[int],
) -> None:
    """
    チップ決済購入者への通知送信

    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        result: 決済結果（ok/ng）
        email: 購入者メールアドレス
        money: 決済金額
    """
    # order_idから recipient_user_id, chip_message_id, message_id を取得
    # 形式: recipient_user_id_chip_message_id_message_id または recipient_user_id_chip_message_id
    order_id_parts = transaction.order_id.split("_")
    recipient_user_id = order_id_parts[0]
    chip_message_id = order_id_parts[1] if len(order_id_parts) > 1 else None

    # 購入者情報取得
    buyer_user = user_crud.get_user_by_id(db, transaction.user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {transaction.user_id}")
        return

    # クリエイター情報取得
    recipient_user = user_crud.get_user_by_id(db, recipient_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {recipient_user_id}")
        return

    recipient_profile = profile_crud.get_profile_by_user_id(db, UUID(recipient_user_id))
    recipient_name = recipient_user.profile_name if recipient_user else "クリエイター"

    # メッセージテキスト取得
    conversation_id = None

    if chip_message_id:
        try:
            chip_message = db.query(ConversationMessages).filter(
                ConversationMessages.id == UUID(chip_message_id)
            ).first()
            if chip_message:
                conversation_id = chip_message.conversation_id
        except Exception as e:
            logger.error(f"Failed to get chip message {chip_message_id}: {e}")
    # チップ金額計算（手数料除く）
    payment_amount = money if money else 0

    # UTCからJSTに変換
    jst = timezone(timedelta(hours=9))
    if transaction.updated_at.tzinfo is None:
        utc_time = transaction.updated_at.replace(tzinfo=timezone.utc)
    else:
        utc_time = transaction.updated_at
    jst_time = utc_time.astimezone(jst)
    payment_date = jst_time.strftime("%Y-%m-%d %H:%M:%S")

    # 通知内容を作成
    if result == RESULT_OK:
        title = f"{recipient_name}にチップ送信が完了しました"
        subtitle = f"{recipient_name}にチップ送信が完了しました"
    else:
        title = "チップの送信に失敗しました"
        subtitle = "チップの送信に失敗しました"

    notification_redirect_url = f"/message/conversation/{conversation_id}" if conversation_id else "/account/sale"

    # メール送信
    try:
        frontend_url = os.environ.get("FRONTEND_URL", "https://mijfans.jp")

        if result == RESULT_OK:
            # 成功時のメール送信
            conversation_url = f"{frontend_url}/message/conversation/{conversation_id}" if conversation_id else ""

            send_chip_payment_buyer_success_email(
                to=email,
                recipient_name=recipient_name,
                conversation_url=conversation_url,
                transaction_id=str(transaction.id),
                payment_amount=payment_amount,
                payment_date=payment_date,
            )
        else:
            # 失敗時のメール送信
            send_payment_faild_email(
                to=email,
                transaction_id=str(transaction.id),
                failure_date=payment_date,
                sendid=transaction.session_id,
                user_name=buyer_user.profile_name,
                user_email=buyer_user.email,
            )
    except Exception as e:
        logger.error(f"Failed to send chip payment buyer email: {e}")

    # 通知を追加
    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
        "redirect_url": notification_redirect_url,
    }

    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": transaction.user_id,
            "type": NotificationType.USERS,
            "payload": payload,
        },
    )


def _send_chip_payment_notifications_for_seller(
    db: Session,
    transaction: PaymentTransactions,
    payment: Payments,
    result: str,
) -> None:
    """
    チップ決済クリエイターへの通知送信

    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        result: 決済結果（ok/ng）
    """
    # 失敗時は通知不要
    if result != RESULT_OK:
        return

    # order_idから recipient_user_id, chip_message_id, message_id を取得
    # 形式: recipient_user_id_chip_message_id_message_id または recipient_user_id_chip_message_id
    order_id_parts = transaction.order_id.split("_")
    recipient_user_id = order_id_parts[0]
    chip_message_id = order_id_parts[1] if len(order_id_parts) > 1 else None

    # クリエイター情報取得
    recipient_user = user_crud.get_user_by_id(db, recipient_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {recipient_user_id}")
        return

    recipient_profile = profile_crud.get_profile_by_user_id(db, UUID(recipient_user_id))

    # 購入者情報取得
    buyer_user = user_crud.get_user_by_id(db, transaction.user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {transaction.user_id}")
        return

    buyer_profile = profile_crud.get_profile_by_user_id(db, transaction.user_id)
    buyer_name = buyer_user.profile_name if buyer_user else "ユーザー"

    # メッセージテキスト取得
    conversation_id = None

    if chip_message_id:
        try:
            chip_message = db.query(ConversationMessages).filter(
                ConversationMessages.id == UUID(chip_message_id)
            ).first()
            if chip_message:
                conversation_id = chip_message.conversation_id
        except Exception as e:
            logger.error(f"Failed to get chip message {chip_message_id}: {e}")

    # チップ金額計算（税込から税抜を計算：整数演算で正確に計算）
    payment_amount = payment.payment_amount if payment.payment_amount else 0
    # payment_amount / 1.1 を整数演算で正確に計算: (payment_amount * 10) // 11
    chip_amount = (payment_amount * 10) // 11

    # プラットフォーム手数料取得
    from app.crud import creator_crud
    creator_info = creator_crud.get_creator_by_user_id(db, UUID(recipient_user_id))
    if not creator_info:
        logger.error(f"Creator info not found: {recipient_user_id}")
        return
    
    # 手数料計算も整数演算で正確に計算
    fee_per_payment = (chip_amount * creator_info.platform_fee_percent) // 100
    # chip_amountから手数料を引いて売上金額を計算
    seller_amount = chip_amount - fee_per_payment

    # UTCからJSTに変換
    jst = timezone(timedelta(hours=9))
    if transaction.updated_at.tzinfo is None:
        utc_time = transaction.updated_at.replace(tzinfo=timezone.utc)
    else:
        utc_time = transaction.updated_at
    jst_time = utc_time.astimezone(jst)
    payment_date = jst_time.strftime("%Y年%m月%d日 %H:%M")

    # 通知内容を作成
    title = f"{buyer_name}さんからチップが届きました"
    subtitle = f"{buyer_name}さんからチップが届きました"
    if conversation_id:
        notification_redirect_url = f"/message/conversation/{conversation_id}"
    else:
        notification_redirect_url = "/account/sale"

    # アバターURLの取得
    avatar_url = "https://logo.mijfans.jp/bimi/logo.svg"
    if buyer_profile and buyer_profile.avatar_url:
        avatar_url = f"{CDN_BASE_URL}/{buyer_profile.avatar_url}"

    # メール送信
    try:
        frontend_url = os.environ.get("FRONTEND_URL", "https://mijfans.jp")
        conversation_url = f"{frontend_url}/message/conversation/{conversation_id}" if conversation_id else ""

        sales_url = f"{frontend_url}/account/sale"
        send_chip_payment_seller_success_email(
            to=recipient_user.email,
            sender_name=buyer_name,
            conversation_url=conversation_url,
            transaction_id=str(transaction.id),
            seller_amount=seller_amount,
            payment_date=payment_date,
            sales_url=sales_url,
        )
    except Exception as e:
        logger.error(f"Failed to send chip payment seller email: {e}")

    # 通知を追加
    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": avatar_url,
        "redirect_url": notification_redirect_url,
    }

    notification = {
        "user_id": UUID(recipient_user_id),
        "type": NotificationType.PAYMENTS,
        "payload": payload,
    }
    notifications_crud.add_notification_for_selling_info(
        db=db, notification=notification
    )


def _send_dm_notification(
    db: Session,
    transaction: PaymentTransactions,
) -> None:
    """プラン加入時のDMの通知を送信"""
    plan = plan_crud.get_plan_by_id(db, transaction.order_id)
    if not plan:
        return

    # welcome_messageがない場合は通知を送信しない
    if plan.welcome_message is None or plan.welcome_message == "":
        return

    creator_user = user_crud.get_user_by_id(db, plan.creator_user_id)
    if not creator_user:
        return

    buyer_user_id = transaction.user_id
    creator_user_id = plan.creator_user_id

    try:
        # DM会話を取得または作成
        conversation = conversations_crud.get_or_create_dm_conversation(
            db=db, user_id_1=creator_user_id, user_id_2=buyer_user_id
        )

        # ウェルカムメッセージを送信（クリエイターから購入者へ）
        message = conversations_crud.create_message(
            db=db,
            conversation_id=conversation.id,
            sender_user_id=creator_user_id,
            body_text=plan.welcome_message,
        )

        logger.info(
            f"Sent welcome message: {message.id} from creator={creator_user_id} to buyer={buyer_user_id} in conversation={conversation.id}"
        )
    except Exception as e:
        logger.error(f"Failed to send DM notification: {e}", exc_info=True)
        # エラーが発生しても決済処理は継続するため、例外は握りつぶす
        return


def _handle_chip_payment_success(
    db: Session,
    transaction: PaymentTransactions,
    payment_amount: int,
    sendid: Optional[str] = None,
    cardbrand: Optional[str] = None,
    cardnumber: Optional[str] = None,
    yuko: Optional[str] = None,
) -> Payments:
    """
    チップ決済成功時の処理

    - conversation_messagesのstatusを0→1に更新
    - 購入者とクリエイターへの通知送信
    - メール送信
    - paymentsレコード作成
    """

    payment_transactions_crud.update_transaction_status(
        db=db,
        transaction_id=transaction.id,
        status=PaymentTransactionStatus.COMPLETED,
    )

    # order_idを分解: recipient_user_id_chip_message_id
    order_id_parts = transaction.order_id.split("_")
    recipient_user_id = order_id_parts[0]
    chip_message_id = order_id_parts[1] if len(order_id_parts) > 1 else None

    # クリエイター情報取得
    from app.crud import creator_crud

    recipient_user = user_crud.get_user_by_id(db, recipient_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {recipient_user_id}")
        raise ValueError(f"Recipient user not found: {recipient_user_id}")

    creator_info = creator_crud.get_creator_by_user_id(db, UUID(recipient_user_id))
    if not creator_info:
        logger.error(f"Creator info not found: {recipient_user_id}")
        raise ValueError(f"Creator info not found: {recipient_user_id}")

    # chip_message_idがある場合、メッセージを有効化
    if chip_message_id:
        try:
            chip_message = db.query(ConversationMessages).filter(
                ConversationMessages.id == UUID(chip_message_id)
            ).first()

            if chip_message:
                payment_completion_time = datetime.now(timezone.utc)
                chip_message.status = ConversationMessageStatus.ACTIVE
                chip_message.created_at = payment_completion_time
                chip_message.updated_at = payment_completion_time
                db.commit()

                # Update conversation's last_message_at to payment completion time
                conversation = chip_message.conversation
                if conversation:
                    conversation.last_message_at = payment_completion_time
                    db.commit()

                logger.info(f"Activated chip payment message: {chip_message_id}")
            else:
                logger.warning(f"Chip message not found for chip_message_id: {chip_message_id}")
        except Exception as e:
            logger.error(f"Failed to activate chip message {chip_message_id}: {e}")

    # チップ金額（手数料除く）
    chip_amount = (payment_amount * 100 + 110 - 1) // 110

    # paymentsレコード作成
    payment = payments_crud.create_payment(
        db=db,
        transaction_id=transaction.id,
        payment_type=PaymentType.CHIP,
        order_id=transaction.order_id,
        order_type=PaymentType.CHIP,
        provider_id=transaction.provider_id,
        provider_payment_id=sendid,
        buyer_user_id=transaction.user_id,
        seller_user_id=recipient_user_id,
        payment_amount=payment_amount,
        payment_price=chip_amount,
        status=PaymentStatus.SUCCEEDED,
        platform_fee=creator_info.platform_fee_percent,
    )

    _update_or_create_user_provider(
        db, transaction, sendid, cardbrand, cardnumber, yuko, True
    )

    return payment


def _handle_chip_payment_failure(
    db: Session,
    payment_amount: int,
    transaction: PaymentTransactions,
) -> None:
    """
    チップ決済失敗時の処理

    - conversation_messagesのdeleted_atを設定
    """
    # order_idを分解: recipient_user_id_chip_message_id_message_id または recipient_user_id_chip_message_id
    order_id_parts = transaction.order_id.split("_")
    recipient_user_id = order_id_parts[0]
    chip_message_id = order_id_parts[1] if len(order_id_parts) > 1 else None
    message_id = order_id_parts[2] if len(order_id_parts) > 2 else None

    payment_transactions_crud.update_transaction_status(
        db=db,
        transaction_id=transaction.id,
        status=PaymentTransactionStatus.FAILED,
    )

    from app.crud import creator_crud
    creator_info = creator_crud.get_creator_by_user_id(db, recipient_user_id)
    if not creator_info:
        logger.error(f"Creator user not found: {recipient_user_id}")
        raise ValueError(f"Creator user not found: {recipient_user_id}")

    chip_amount = (payment_amount * 100 + 110 - 1) // 110

    # chip_message_idがある場合、メッセージを削除
    if chip_message_id:
        try:
            chip_message = db.query(ConversationMessages).filter(
                ConversationMessages.id == UUID(chip_message_id)
            ).first()

            if chip_message:
                from datetime import datetime, timezone
                chip_message.deleted_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Marked chip payment message as deleted: {chip_message_id}")
            else:
                logger.warning(f"Chip message not found for chip_message_id: {chip_message_id}")
        except Exception as e:
            logger.error(f"Failed to delete chip message {chip_message_id}: {e}")

    # メッセージIDがある場合、メッセージを削除
    if message_id:
        try:
            message = db.query(ConversationMessages).filter(
                ConversationMessages.id == UUID(message_id)
            ).first()

            if message:
                from datetime import datetime, timezone
                message.deleted_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Marked chip payment message as deleted: {message_id}")
            else:
                logger.warning(f"Message not found for message_id: {message_id}")
        except Exception as e:
            logger.error(f"Failed to delete message {message_id}: {e}")


    payment = payments_crud.create_payment(
        db=db,
        transaction_id=transaction.id,
        payment_type=PaymentType.CHIP,
        order_id=transaction.order_id,
        order_type=PaymentType.CHIP,
        provider_id=transaction.provider_id,
        provider_payment_id=transaction.session_id,
        buyer_user_id=transaction.user_id,
        seller_user_id=recipient_user_id,
        payment_amount=payment_amount,
        payment_price=chip_amount,
        status=PaymentStatus.FAILED,
        platform_fee=creator_info.platform_fee_percent,
    )

    logger.info(f"Chip payment failure processed: transaction_id={transaction.id}")

    return payment


@router.get("/payment")
async def payment_webhook(
    clientip: Optional[str] = Query(None, alias="clientip"),
    telno: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    sendid: Optional[str] = Query(None),
    sendpoint: Optional[str] = Query(None),
    cardbrand: Optional[str] = Query(None),
    cardnumber: Optional[str] = Query(None),
    yuko: Optional[str] = Query(None),
    result: Optional[str] = Query(None),
    money: Optional[int] = Query(None),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    """
    CREDIX決済結果Webhook

    URL形式: /payment?clientip=***&telno=***&email=***&sendid=***&sendpoint=***&result=***&money=***

    Args:
        clientip: クライアントIP
        telno: 電話番号
        email: メールアドレス
        sendid: カードID
        sendpoint: フリーパラメータ（transaction_idを含む想定）
        result: 決済結果（ok/ng）
        money: 決済金額
    """
    try:
        _log_webhook_received(
            clientip,
            telno,
            email,
            sendid,
            sendpoint,
            result,
            money,
            cardbrand,
            cardnumber,
            yuko,
        )

        # sendpointからtransaction_idを抽出
        if not sendpoint:
            logger.error("sendpoint is required")
            return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)

        try:
            sendpoint_parts = sendpoint.split("_")
            if len(sendpoint_parts) < 2:
                raise ValueError(f"Invalid sendpoint format: {sendpoint}")
            transaction_origin = sendpoint_parts[0]
            transaction_id = sendpoint_parts[1]
        except (ValueError, IndexError) as e:
            logger.error(f"Failed to parse sendpoint: {e}")
            return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)

        # トランザクション取得
        transaction = payment_transactions_crud.get_transaction_by_id(
            db, transaction_id
        )
        if not transaction:
            logger.error(f"Transaction not found: {transaction_id}")
            return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)

        # 決済結果に応じて処理を分岐
        is_success = result == RESULT_OK
        payment_amount = money if money else 0
        is_chip_payment = transaction.type == PaymentTransactionType.CHIP

        if is_success:
            # 成功時の処理
            if is_chip_payment:
                payment = _handle_chip_payment_success(
                    db=db,
                    transaction=transaction,
                    payment_amount=payment_amount,
                    sendid=sendid,
                    cardbrand=cardbrand,
                    cardnumber=cardnumber,
                    yuko=yuko,
                )
            else:
                payment = _handle_successful_payment(
                    db=db,
                    transaction=transaction,
                    payment_amount=payment_amount,
                    send_id=sendid,
                    email=email,
                    cardbrand=cardbrand,
                    cardnumber=cardnumber,
                    yuko=yuko,
                    transaction_origin=transaction_origin,
                )

            # プラン加入時のDMの通知を送信
            if transaction.type == PaymentTransactionType.SUBSCRIPTION:
                _send_dm_notification(db, transaction)
        else:
            # 失敗時の処理
            if is_chip_payment:
                payment = _handle_chip_payment_failure(
                    db=db,
                    transaction=transaction,
                    payment_amount=payment_amount,
                )
            else:
                payment = _handle_failed_payment(
                    db=db,
                    transaction=transaction,
                    payment_amount=payment_amount,
                    transaction_origin=transaction_origin
                )


        # チップ決済の場合は専用の通知関数を呼び出す
        if is_chip_payment:
            # order_idから recipient_user_id を取得
            order_id_parts = transaction.order_id.split("_")
            recipient_user_id = order_id_parts[0]

            # 購入者とクリエイターの通知設定を取得
            send_notification_buyer, send_notification_seller = (
                _get_buyer_and_seller_need_to_send_notification(
                    db, transaction.user_id, UUID(recipient_user_id)
                )
            )

            # 購入者への通知
            if send_notification_buyer:
                _send_chip_payment_notifications_for_buyer(
                    db=db,
                    transaction=transaction,
                    result=result,
                    email=email,
                    money=money,
                )

            # クリエイターへの通知
            if send_notification_seller:
                _send_chip_payment_notifications_for_seller(
                    db=db,
                    transaction=transaction,
                    payment=payment,
                    result=result,
                )
        else:
            # 通常の決済の場合
            # get buyer and seller setting notification
            send_notification_buyer, send_notification_seller = (
                _get_buyer_and_seller_need_to_send_notification(
                    db, payment.buyer_user_id, payment.seller_user_id
                )
            )
            # 0円決済（無料）の場合は決済通知を送信しない
            if transaction_origin != TransactionType.PAYMENT_ORIGIN_FREE:
                if send_notification_buyer:
                    # 決済通知を送信 (バッチからの失敗時、またはフロントエンドからのリクエスト時)
                    _send_payment_notifications_for_buyer(
                        db=db,
                        result=result,
                        transaction=transaction,
                        send_id=sendid,
                        email=email,
                        money=money,
                        transaction_origin=transaction_origin,
                    )
                if send_notification_seller:
                    # 決済通知を追加
                    _add_payment_notifications_for_seller(
                        db=db,
                        result=result,
                        transaction=transaction,
                        transaction_origin=transaction_origin,
                    )

        # トランザクションをリフレッシュ
        db.refresh(transaction)

        return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)

    except ValueError as e:
        # 注文情報が見つからない場合など、ビジネスロジックエラー
        logger.exception(f"Payment webhook validation error: {e}")
        db.rollback()
        return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)

    except Exception as e:
        # 予期しないエラー
        logger.error(f"Payment webhook failed: {e}", exc_info=True)
        db.rollback()
        return PlainTextResponse(content=CREDIX_ERROR_RESPONSE, status_code=200)

    finally:
        logger.info("=== CREDIX Webhook受信完了 ===")


def _get_buyer_and_seller_need_to_send_notification(
    db: Session,
    buyer_user_id: UUID,
    seller_user_id: UUID,
) -> Tuple[bool, bool]:
    """バイヤーとセラーの通知設定を取得"""
    send_notification_buyer = True
    send_notification_seller = True
    buyer_settings = get_user_settings_by_user_id(
        db, buyer_user_id, UserSettingsType.EMAIL
    )
    seller_settings = get_user_settings_by_user_id(
        db, seller_user_id, UserSettingsType.EMAIL
    )

    if buyer_settings:
        buyer_setting = buyer_settings.settings.get("userPayments", True)
        if not buyer_setting:
            send_notification_buyer = False
    if seller_settings:
        seller_setting = seller_settings.settings.get("creatorPayments", True)
        if not seller_setting:
            send_notification_seller = False

    return send_notification_buyer, send_notification_seller
