"""
CREDIX決済Webhookエンドポイント
"""
from fastapi import APIRouter, Query, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from typing import Optional, Tuple
from uuid import UUID
from datetime import datetime, timedelta, timezone
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
)
from app.constants.enums import (
    PaymentTransactionStatus,
    PaymentTransactionType,
    PaymentStatus,
    SubscriptionType,
    SubscriptionStatus,
    TransactionType,
)
from app.services.email.send_email import send_payment_succuces_email, send_payment_faild_email, send_selling_info_email
from app.models.payment_transactions import PaymentTransactions
from app.models.payments import Payments
from app.models.subscriptions import Subscriptions
import os

CDN_BASE_URL = os.environ.get('CDN_BASE_URL')

logger = Logger.get_logger()
router = APIRouter()

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
) -> Tuple[int, UUID]:
    """
    注文情報（価格と売主ユーザーID）を取得
    
    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        
    Returns:
        (payment_price, seller_user_id) のタプル
        
    Raises:
        ValueError: 注文情報が見つからない場合
    """
    payment_type = (
        PaymentTransactionType.SINGLE
        if transaction.type == PaymentTransactionType.SINGLE
        else PaymentTransactionType.SUBSCRIPTION
    )

    if payment_type == PaymentTransactionType.SINGLE:
        price, post, creator = price_crud.get_price_and_post_by_id(db, transaction.order_id)
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
    """
    # コンテンツ情報を取得
    payment_type = (
        PaymentTransactionType.SINGLE
        if transaction.type == PaymentTransactionType.SINGLE
        else PaymentTransactionType.SUBSCRIPTION
    )

    if payment_type == PaymentTransactionType.SINGLE:
        price, post = price_crud.get_price_and_post_by_id(db, transaction.order_id)
        if not price or not post:
            raise ValueError(f"Price or post not found: {transaction.order_id}")
        contents_name = post.description
        # 通知用に相対パスのみを返す
        content_url = f"/post/detail?post_id={post.id}"

    else:  # SUBSCRIPTION
        plan = plan_crud.get_plan_by_id(db, transaction.order_id)
        if not plan:
            raise ValueError(f"Plan not found: {transaction.order_id}")
        contents_name = plan.name
        # 通知用に相対パスのみを返す
        content_url = f"/plan/{plan.id}"

    return content_url, contents_name


def _get_selling_info(
    db: Session,
    transaction: PaymentTransactions,
) -> Tuple[str, str]:
    """
    売り上げ情報を取得
    """
    # コンテンツ情報を取得
    contents_type = (
        PaymentTransactionType.SINGLE
        if transaction.type == PaymentTransactionType.SINGLE
        else PaymentTransactionType.SUBSCRIPTION
    )

    if contents_type == PaymentTransactionType.SINGLE:
        price, post = price_crud.get_price_and_post_by_id(db, transaction.order_id)
        if not price or not post:
            raise ValueError(f"Price or post not found: {transaction.order_id}")

        seller_user_id = post.creator_user_id
        contents_name = post.description
        content_url = f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/post/detail?post_id={post.id}"

    else:  # SUBSCRIPTION
        plan = plan_crud.get_plan_by_id(db, transaction.order_id)
        if not plan:
            raise ValueError(f"Plan not found: {transaction.order_id}")

        seller_user_id = plan.creator_user_id
        contents_name = plan.name
        content_url = f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/plan/{plan.id}"

    seller_user = user_crud.get_user_by_id(db, seller_user_id)
    seller_name = seller_user.profile_name
    seller_email = seller_user.email

    return content_url, contents_name, seller_name, seller_user_id, seller_email, contents_type

def _create_payment_record(
    db: Session,
    transaction: PaymentTransactions,
    payment_price: int,
    seller_user_id: UUID,
    payment_amount: int,
    platform_fee: int,
    status: int = PaymentStatus.SUCCEEDED,
) -> Payments:
    """
    決済レコードを作成
    
    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        payment_price: 商品価格
        seller_user_id: 売主ユーザーID
        payment_amount: 決済金額
        platform_fee: プラットフォーム手数料
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

    access_start = datetime.utcnow()
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
        order_type=transaction.type,
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
) -> None:
    """
    ユーザープロバイダー情報を更新または作成
    
    Args:
        db: データベースセッション
        transaction: 決済トランザクション
        send_id: CREDIXのsendid
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
    """
    logger.info(f"決済成功: transaction_id={transaction.id}")

    # トランザクションステータスを完了に更新
    payment_transactions_crud.update_transaction_status(
        db=db,
        transaction_id=transaction.id,
        status=PaymentTransactionStatus.COMPLETED,
    )

    # 注文情報を取得
    try:
        payment_price, seller_user_id, platform_fee = _get_order_info(db, transaction)
    except ValueError as e:
        logger.error(str(e))
        raise

    # 決済レコードを作成
    payment = _create_payment_record(
        db=db,
        transaction=transaction,
        payment_price=payment_price,
        seller_user_id=seller_user_id,
        platform_fee=platform_fee,
        payment_amount=payment_amount,
    )

    # サブスクリプションレコードを作成
    subscription = _create_subscription_record(
        db=db,
        transaction=transaction,
        seller_user_id=seller_user_id,
        payment_id=payment.id,
    )

    # ユーザープロバイダー情報を更新または作成
    _update_or_create_user_provider(db, transaction, send_id, cardbrand, cardnumber, yuko)

    logger.info(f"Payment created: {payment.id}")
    logger.info(f"Subscription created: {subscription.id}")


def _handle_failed_payment(
    db: Session,
    transaction: PaymentTransactions,
    payment_amount: int,
) -> None:
    """
    決済失敗時の処理
    
    Args:
        db: データベースセッション
        transaction: 決済トランザクション
    """
    logger.info(f"決済失敗: transaction_id={transaction.id}")

    # トランザクションステータスを失敗に更新
    payment_transactions_crud.update_transaction_status(
        db=db,
        transaction_id=transaction.id,
        status=PaymentTransactionStatus.FAILED,
    )

    # トランザクションを取得
    payment_transaction = payment_transactions_crud.get_transaction_by_id(db, transaction.id)
    if not payment_transaction:
        logger.error(f"Payment transaction not found: {transaction.id}")
        return

    payment_price, seller_user_id, platform_fee = _get_order_info(db, payment_transaction)

    # 決済レコードを作成
    _create_payment_record(
        db=db,
        transaction=transaction,
        payment_price=payment_price,
        seller_user_id=seller_user_id,
        platform_fee=platform_fee,
        payment_amount=payment_amount,
        status=PaymentStatus.FAILED,
    )

def _send_payment_notifications_for_buyer(
    db: Session,
    result: str,
    send_id: Optional[str],
    email: Optional[str],
    money: Optional[int],
    transaction: PaymentTransactions,
) -> None:
    """
    決済成功・失敗時のメール送信と通知追加
    """

    #　購入者ユーザー情報を取得
    buyer_user = user_crud.get_user_by_id(db, transaction.user_id)
    user_name = buyer_user.profile_name
    purchase_history_url = f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/bought/post"
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
    frontend_url = os.environ.get('FRONTEND_URL', 'https://mijfans.jp')
    email_content_url = f"{frontend_url}{notification_redirect_url}"

    # 通知内容を作成
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
    notification = {
        "user_id": buyer_user.id,
        "type": NotificationType.USERS,
        "payload": payload,
    }
    notifications_crud.add_notification_for_payment_succuces(db=db, notification=notification)


def _add_payment_notifications_for_seller(
    db: Session,
    transaction: PaymentTransactions,
) -> None:
    """販売者への決済通知を追加"""
    buyer_user = user_crud.get_user_by_id(db, transaction.user_id)
    buyer_name = buyer_user.profile_name

    # 通知用は相対パス
    notification_redirect_url = "/account/sale"

    # メール用は完全なURL
    dashboard_url = f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/account/sale"

    content_url, contents_name, seller_name, seller_user_id, seller_email, contents_type = _get_selling_info(db, transaction)


    if contents_type == PaymentTransactionType.SINGLE:
        title = f"{buyer_name}さんが{contents_name}を購入しました"
        subtitle = f"{buyer_name}さんが{contents_name}を購入しました"
    else:
        title = f"{buyer_name}さんが{contents_name}プランに加入しました"
        subtitle = f"{buyer_name}さんが{contents_name}プランに加入しました"


    # アバターURLの取得（buyer_userのprofileが存在するか確認）
    avatar_url = "https://logo.mijfans.jp/bimi/logo.svg"

    if hasattr(buyer_user, 'profile') and buyer_user.profile:
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
    notifications_crud.add_notification_for_selling_info(db=db, notification=notification)

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
        _log_webhook_received(clientip, telno, email, sendid, sendpoint, result, money, cardbrand, cardnumber, yuko)

        # sendpointからtransaction_idを抽出
        if not sendpoint:
            logger.error("sendpoint is required")
            return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)


        transaction_origin = sendpoint.split("_")[0]
        transaction_id = sendpoint.split("_")[1]

        # トランザクション取得
        transaction = payment_transactions_crud.get_transaction_by_id(
            db, transaction_id
        )
        if not transaction:
            logger.error(f"Transaction not found: {transaction_id}")
            return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)

        # 決済結果に応じて処理を分岐
        is_success = result == "ok"
        payment_amount = money if money else 0


        if is_success:
            # フロントエンドからのリクエストの場合は決済処理を行う
            if transaction_origin == TransactionType.PAYMENT_ORIGIN_FRONT:
                _handle_successful_payment(db, transaction, payment_amount, sendid, email, cardbrand, cardnumber, yuko)
            else:
                # TODO: バッチからのリクエストの場合は決済処理を行う
                return
        else:
            _handle_failed_payment(db, transaction, payment_amount)

        # 決済通知を送信
        _send_payment_notifications_for_buyer(
            db=db,
            result=result,
            transaction=transaction,
            send_id=sendid,
            email=email,
            money=money,
        )

        # 決済通知を追加
        if result == RESULT_OK:
            _add_payment_notifications_for_seller(
                db=db,
                transaction=transaction,
            )

        # トランザクションをリフレッシュ
        db.refresh(transaction)

        return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)

    except ValueError as e:
        # 注文情報が見つからない場合など、ビジネスロジックエラー
        logger.error(f"Payment webhook validation error: {e}")
        db.rollback()
        return PlainTextResponse(content=CREDIX_SUCCESS_RESPONSE, status_code=200)

    except Exception as e:
        # 予期しないエラー
        logger.error(f"Payment webhook failed: {e}", exc_info=True)
        db.rollback()
        return PlainTextResponse(content=CREDIX_ERROR_RESPONSE, status_code=200)

    finally:
        logger.info("=== CREDIX Webhook受信完了 ===")
