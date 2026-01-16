"""
Albatal決済Webhookエンドポイント
"""

from fastapi import APIRouter, Depends, Form, Response
from sqlalchemy.orm import Session
from typing import Optional, Tuple
from uuid import UUID
from datetime import datetime, timedelta, timezone
import os

from app.db.base import get_db
from app.core.logger import Logger
from app.services.slack.slack import SlackService
from app.api.commons.function import CommonFunction
from app.schemas.notification import NotificationType
from app.constants.enums import (
    PaymentTransactionType,
    PaymentType,
    ItemType,
    SubscriptionType,
    PaymentTransactionStatus,
    PaymentStatus,
    ConversationMessageStatus,
    SubscriptionStatus,
)
from app.models.payments import Payments
from app.models.payment_transactions import PaymentTransactions
from app.models.conversation_messages import ConversationMessages
from app.models.prices import Prices
from app.models.posts import Posts
from app.models.creators import Creators
from app.models.plans import Plans
from app.crud import (
    payment_transactions_crud,
    providers_crud,
    price_crud,
    plan_crud,
    payments_crud,
    subscriptions_crud,
    user_providers_crud,
    user_crud,
    conversations_crud,
    creator_crud,
    notifications_crud,
)
from app.services.email.send_email import (
    send_chip_payment_buyer_success_email,
    send_chip_payment_seller_success_email,
    send_payment_succuces_email,
    send_selling_info_email,
    send_payment_faild_email,
    send_buyer_cancel_subscription_email,
)

logger = Logger.get_logger()
router = APIRouter()
slack_alert = SlackService.initialize()

# 定数
CDN_BASE_URL = os.environ.get("CDN_BASE_URL", "https://cdn.mijfans.jp")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://mijfans.jp")
ALBATAL_SUCCESS_RESPONSE = "successok"
ALBATAL_APPROVED_STATUS = "approved"
DEFAULT_AVATAR_URL = "https://logo.mijfans.jp/bimi/logo.svg"
SUBSCRIPTION_DURATION_DAYS = 30
JST_TIMEZONE = timezone(timedelta(hours=9))

########################################################
# 共通ユーティリティ関数
########################################################


def _convert_utc_to_jst(utc_datetime: datetime) -> str:
    """UTC時刻をJSTに変換して文字列で返す"""
    if utc_datetime.tzinfo is None:
        utc_time = utc_datetime.replace(tzinfo=timezone.utc)
    else:
        utc_time = utc_datetime
    jst_time = utc_time.astimezone(JST_TIMEZONE)
    return jst_time.strftime("%Y-%m-%d %H:%M:%S")


def _calculate_payment_price_from_amount(payment_amount: int) -> int:
    """税込金額から税抜金額を計算（整数演算）"""
    return (payment_amount * 100 + 110 - 1) // 110


def _calculate_chip_amount_from_payment(payment_amount: int) -> int:
    """チップ金額を計算（税込から税抜：整数演算）"""
    return (payment_amount * 10) // 11


def _calculate_seller_amount(chip_amount: int, platform_fee_percent: int) -> int:
    """売上金額を計算（チップ金額から手数料を引く）"""
    fee_per_payment = (chip_amount * platform_fee_percent) // 100
    return chip_amount - fee_per_payment


def _get_user_avatar_url(user) -> str:
    """ユーザーのアバターURLを取得"""
    if user and user.profile and user.profile.avatar_url:
        return f"{CDN_BASE_URL}/{user.profile.avatar_url}"
    return DEFAULT_AVATAR_URL


def _get_conversation_id_from_chip_message(
    db: Session, chip_message_id: Optional[str]
) -> Optional[UUID]:
    """チップメッセージIDから会話IDを取得"""
    if not chip_message_id:
        return None
    try:
        chip_message = db.query(ConversationMessages).filter(
            ConversationMessages.id == UUID(chip_message_id)
        ).first()
        return chip_message.conversation_id if chip_message else None
    except (ValueError, AttributeError):
        return None


def _get_seller_info_by_transaction_type(
    db: Session,
    transaction_type: int,
    order_id: str,
) -> Optional[Tuple[UUID, int, int, int]]:
    """決済タイプに応じて売り手情報を取得"""
    if transaction_type == PaymentTransactionType.SINGLE:
        price, post, creator = _get_single_seller_info(db, order_id)
        if not price or not post or not creator:
            return None
        return (
            post.creator_user_id,
            creator.platform_fee_percent,
            PaymentType.SINGLE,
            ItemType.POST,
        )
    elif transaction_type == PaymentTransactionType.SUBSCRIPTION:
        plan, creator = _get_subscription_seller_info(db, order_id)
        if not plan or not creator:
            return None
        return (
            plan.creator_user_id,
            creator.platform_fee_percent,
            PaymentType.PLAN,
            ItemType.PLAN,
        )
    return None

########################################################
# ログ関数
########################################################


def _log_wpf_webhook_received(
    wpf_transaction_id: Optional[str],
    wpf_status: Optional[str],
    wpf_unique_id: Optional[str],
    payment_transaction_unique_id: Optional[str],
    payment_transaction_amount: Optional[str],
    consumer_id: Optional[str],
    notification_type: Optional[str],
    signature: Optional[str],
) -> None:
    """Albatalウェブフック通知受信ログを出力"""
    logger.info(f"Albatal WPF決済完了通知受信: wpf_transaction_id={wpf_transaction_id}, "
                f"wpf_status={wpf_status}, wpf_unique_id={wpf_unique_id}, "
                f"payment_transaction_unique_id={payment_transaction_unique_id}, "
                f"amount={payment_transaction_amount}, consumer_id={consumer_id}, "
                f"notification_type={notification_type}, signature={signature}")

def _log_recurring_webhook_received(
    transaction_id: Optional[str],
    unique_id: Optional[str],
    merchant_transaction_id: Optional[str],
    status: Optional[str],
    amount: Optional[str],
) -> None:
    """Albatal定期決済通知受信ログを出力"""
    logger.info(f"Albatal定期決済通知受信: transaction_id={transaction_id}, "
                f"unique_id={unique_id}, merchant_transaction_id={merchant_transaction_id}, "
                f"status={status}, amount={amount}")


########################################################
# エンドポイント
########################################################


@router.post("/payment")
async def receive_albatal_payment_webhook(
    # WPF決済完了通知パラメータ
    wpf_transaction_id: Optional[str] = Form(None),
    wpf_status: Optional[str] = Form(None),
    wpf_unique_id: Optional[str] = Form(None),
    payment_transaction_unique_id: Optional[str] = Form(None),
    payment_transaction_amount: Optional[str] = Form(None),
    consumer_id: Optional[str] = Form(None),
    notification_type: Optional[str] = Form(None),
    signature: Optional[str] = Form(None),
    # 定期決済通知パラメータ
    transaction_id: Optional[str] = Form(None),
    unique_id: Optional[str] = Form(None),
    merchant_transaction_id: Optional[str] = Form(None),
    status: Optional[str] = Form(None),
    amount: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    Albatalウェブフック通知受信エンドポイント

    2種類の通知に対応：
    1. WPF決済完了通知
    2. 定期決済（Managed Recurring）通知
    """
    try:
        if wpf_status:
            # 初回決済完了通知の場合

            _log_wpf_webhook_received(
                wpf_transaction_id,
                wpf_status,
                wpf_unique_id,
                payment_transaction_unique_id,
                payment_transaction_amount,
                consumer_id,
                notification_type,
                signature,
            )
            _handle_wpf_payment(
                db,
                wpf_transaction_id,
                wpf_status,
                wpf_unique_id,
                payment_transaction_unique_id,
                payment_transaction_amount,
                consumer_id,
                notification_type,
                signature,
            )
        
        elif status:
            _log_recurring_webhook_received(
                transaction_id,
                unique_id,
                merchant_transaction_id,
                status,
                amount,
            )


            _handle_recurring_payment(
                db,
                merchant_transaction_id,
                status,
                amount,
            )
        logger.info(f"Albatalウェブフック通知処理完了")
        return Response(content=ALBATAL_SUCCESS_RESPONSE, status_code=200)

    except Exception as e:
        logger.error(f"Albatalウェブフック処理エラー: {str(e)}", exc_info=True)
        # Albatalへのエラー応答はHTTP 200で返す（再送信を避けるため）
        return Response(content=ALBATAL_SUCCESS_RESPONSE, status_code=200)

@router.post("/payment/chip")
async def receive_albatal_chip_payment_webhook(
    wpf_transaction_id: Optional[str] = Form(None),
    wpf_status: Optional[str] = Form(None),
    wpf_unique_id: Optional[str] = Form(None),
    payment_transaction_unique_id: Optional[str] = Form(None),
    payment_transaction_amount: Optional[str] = Form(None),
    consumer_id: Optional[str] = Form(None),
    notification_type: Optional[str] = Form(None),
    signature: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Albatal投げ銭決済完了通知受信エンドポイント"""
    try:
        _log_wpf_webhook_received(
            wpf_transaction_id,
            wpf_status,
            wpf_unique_id,
            payment_transaction_unique_id,
            payment_transaction_amount,
            consumer_id,
            notification_type,
            signature,
        )
        _handle_wpf_chip_payment(
            db,
            wpf_transaction_id,
            wpf_status,
            wpf_unique_id,
            payment_transaction_unique_id,
            payment_transaction_amount,
            consumer_id,
        )
      
        
        return Response(content=ALBATAL_SUCCESS_RESPONSE, status_code=200)
    except Exception as e:
        logger.error(f"Albatal投げ銭決済完了通知受信エンドポイントエラー: {str(e)}", exc_info=True)
        return Response(content=ALBATAL_SUCCESS_RESPONSE, status_code=200)


########################################################
# 決済処理関数
########################################################

def _handle_wpf_payment(
    db: Session,
    wpf_transaction_id: Optional[str],
    wpf_status: Optional[str],
    wpf_unique_id: Optional[str],
    payment_transaction_unique_id: Optional[str],
    payment_transaction_amount: Optional[str],
    consumer_id: Optional[str],
    notification_type: Optional[str],
    signature: Optional[str],
) -> None:
    """
    Albatal初回決済完了通知の処理
    """
    payment_transaction = payment_transactions_crud.get_transaction_by_id(db, wpf_transaction_id)
    if not payment_transaction:
        logger.error(f"Payment transaction not found: {payment_transaction_unique_id}")
        return

    if wpf_status == ALBATAL_APPROVED_STATUS:
        payment = _handle_wpf_payment_success(
            db,
            wpf_unique_id,
            payment_transaction_amount,
            payment_transaction,
            consumer_id,
        )

        if payment:
            _handle_payment_success_notification(db, payment)
    else:
        _handle_wpf_payment_failure(
            db,
            payment_transaction,
        )
        if payment_transaction_unique_id is not None:
            _handle_payment_failure_notification(db, payment_transaction)
    return

def _handle_wpf_payment_success(
    db: Session,
    wpf_unique_id: Optional[str],
    payment_transaction_amount: Optional[str],
    payment_transaction: Optional[PaymentTransactions],
    consumer_id: Optional[str],
) -> Optional[Payments]:
    """Albatal初回決済完了通知の処理"""
    provider = providers_crud.get_provider_by_code(db, "albatal")
    if not provider:
        logger.error("Albatal provider not found")
        return None

    buyer_user_id = payment_transaction.user_id
    payment_amount = int(payment_transaction_amount)
    payment_price = _calculate_payment_price_from_amount(payment_amount)
    order_id = payment_transaction.order_id

    # 決済タイプに応じて売り手情報を取得
    seller_info = _get_seller_info_by_transaction_type(
        db, payment_transaction.type, order_id
    )
    if not seller_info:
        logger.error(f"Invalid payment transaction type: {payment_transaction.type}")
        return None

    seller_user_id, platform_fee, payment_type, order_type = seller_info

    # プラン決済の場合はウェルカムメッセージを送信
    if payment_transaction.type == PaymentTransactionType.SUBSCRIPTION:
        plan, _ = _get_subscription_seller_info(db, order_id)
        if plan:
            _handle_plan_payment_success(db, plan, payment_transaction)

    # 決済レコードを作成
    payment = _create_payment_record(
        db,
        order_id,
        wpf_unique_id,
        PaymentStatus.SUCCEEDED,
        payment_transaction.id,
        payment_type,
        order_type,
        provider.id,
        buyer_user_id,
        seller_user_id,
        payment_amount,
        payment_price,
        platform_fee,
        datetime.now(timezone.utc),
    )
    if not payment:
        logger.error(f"Payment record not created: {payment_transaction.id}")
        return None
    logger.info(f"Payment record created: {payment.id}")

    # サブスクリプションレコードを作成
    access_type = (
        SubscriptionType.PLAN if payment_type == PaymentType.PLAN else SubscriptionType.SINGLE
    )
    next_billing_date = (
        datetime.now(timezone.utc) + timedelta(days=SUBSCRIPTION_DURATION_DAYS)
        if payment_type == PaymentType.PLAN
        else None
    )

    _create_subscription_record(
        db,
        buyer_user_id,
        SubscriptionStatus.ACTIVE,
        access_type,
        seller_user_id,
        order_id,
        order_type,
        datetime.now(timezone.utc),
        next_billing_date,
        provider.id,
        payment.id,
        next_billing_date,
    )

    # トランザクションステータスを更新
    payment_transactions_crud.update_transaction_status(
        db,
        payment_transaction.id,
        PaymentTransactionStatus.COMPLETED,
    )

    # ユーザープロバイダーを有効化
    _handle_update_creator_user_provider(db, buyer_user_id, consumer_id, provider.id)

    logger.info(f"Payment transaction status updated: {payment_transaction.id}")
    return payment

def _handle_plan_payment_success(
    db: Session,
    plan: Optional[Plans],
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """プラン加入時のウェルカムメッセージを送信"""
    # welcome_messageがない場合は通知を送信しない
    if not plan or not plan.welcome_message or plan.welcome_message == "":
        return

    creator_user = user_crud.get_user_by_id(db, plan.creator_user_id)
    if not creator_user:
        return

    buyer_user_id = payment_transaction.user_id
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
            f"Sent welcome message: {message.id} from creator={creator_user_id} "
            f"to buyer={buyer_user_id} in conversation={conversation.id}"
        )
    except Exception as e:
        logger.error(f"Failed to send DM notification: {e}", exc_info=True)
        # エラーが発生しても決済処理は継続するため、例外は握りつぶす
    
def _handle_wpf_payment_failure(
    db: Session,
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """
    Albatal初回決済失敗通知の処理
    """
    # トランザクションを更新
    payment_transactions_crud.update_transaction_status(
        db,
        payment_transaction.id,
        PaymentTransactionStatus.FAILED,
    )
    return

########################################################
# 投げ銭決済関連処理
########################################################

def _handle_wpf_chip_payment(
    db: Session,
    wpf_transaction_id: Optional[str],
    wpf_status: Optional[str],
    wpf_unique_id: Optional[str],
    payment_transaction_unique_id: Optional[str],
    payment_transaction_amount: Optional[str],
    consumer_id: Optional[str],
) -> None:
    """
    Albatal投げ銭決済完了通知の処理
    """
    payment_transaction = payment_transactions_crud.get_transaction_by_id(db, wpf_transaction_id)
    if not payment_transaction:
        logger.error(f"Payment transaction not found: {payment_transaction_unique_id}")
        return

    if wpf_status == ALBATAL_APPROVED_STATUS:
        payment = _handle_wpf_chip_payment_success(
            db,
            wpf_unique_id,
            payment_transaction_amount,
            payment_transaction,
            consumer_id,
        )

        # 決済完了通知を送信
        if payment:
            _send_chip_payment_success_notification(db, payment)
    else:
        _handle_wpf_chip_payment_failure(
            db,
            payment_transaction,
        )
        if payment_transaction_unique_id is not None:
            _handle_payment_failure_notification(db, payment_transaction)
    return

def _handle_wpf_chip_payment_success(
    db: Session,
    wpf_unique_id: Optional[str],
    payment_transaction_amount: Optional[str],
    payment_transaction: Optional[PaymentTransactions],
    consumer_id: Optional[str],
) -> Optional[Payments]:
    """Albatal投げ銭決済完了通知の処理"""
    provider = providers_crud.get_provider_by_code(db, "albatal")
    if not provider:
        logger.error("Albatal provider not found")
        return None

    buyer_user_id = payment_transaction.user_id
    payment_amount = int(payment_transaction_amount)
    order_id = payment_transaction.order_id

    # order_idを分解: recipient_user_id_chip_message_id
    order_id_parts = order_id.split("_")
    if len(order_id_parts) < 2:
        logger.error(f"Invalid order_id format: {order_id}")
        return None

    recipient_user_id = order_id_parts[0]
    chip_message_id = order_id_parts[1]

    # 受取人ユーザーとクリエイター情報を取得
    recipient_user = user_crud.get_user_by_id(db, recipient_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {recipient_user_id}")
        return None

    creator_info = creator_crud.get_creator_by_user_id(db, UUID(recipient_user_id))
    if not creator_info:
        logger.error(f"Creator info not found: {recipient_user_id}")
        return None

    # チップメッセージを更新
    chip_message = db.query(ConversationMessages).filter(
        ConversationMessages.id == UUID(chip_message_id)
    ).first()
    if not chip_message:
        logger.error(f"Chip message not found: {chip_message_id}")
        return None

    now = datetime.now(timezone.utc)
    chip_message.status = ConversationMessageStatus.ACTIVE
    chip_message.created_at = now
    chip_message.updated_at = now
    db.commit()

    # 会話の最終メッセージ時刻を更新
    if chip_message.conversation:
        chip_message.conversation.last_message_at = now
        db.commit()

    # チップ金額を計算
    chip_amount = _calculate_payment_price_from_amount(payment_amount)

    # 決済レコードを作成
    payment = _create_payment_record(
        db,
        order_id,
        wpf_unique_id,
        PaymentStatus.SUCCEEDED,
        payment_transaction.id,
        PaymentType.CHIP,
        PaymentType.CHIP,
        provider.id,
        buyer_user_id,
        recipient_user_id,
        payment_amount,
        chip_amount,
        creator_info.platform_fee_percent,
        now,
    )
    if not payment:
        logger.error(f"Payment record not created: {payment_transaction.id}")
        return None
    logger.info(f"Payment record created: {payment.id}")

    # トランザクションステータスを更新
    payment_transactions_crud.update_transaction_status(
        db,
        payment_transaction.id,
        PaymentTransactionStatus.COMPLETED,
    )

    # ユーザープロバイダーを有効化
    _handle_update_creator_user_provider(db, buyer_user_id, consumer_id, provider.id)

    logger.info(f"Payment transaction status updated: {payment_transaction.id}")
    return payment

def _handle_wpf_chip_payment_failure(
    db: Session,
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """
    Albatal投げ銭決済失敗通知の処理
    """
    payment_transactions_crud.update_transaction_status(
        db,
        payment_transaction.id,
        PaymentTransactionStatus.FAILED,
    )

    order_id_parts = payment_transaction.order_id.split("_")
    chip_message_id = order_id_parts[1] if len(order_id_parts) > 1 else None

    # メッセージを削除
    if chip_message_id:
        try:
            chip_message = db.query(ConversationMessages).filter(
                ConversationMessages.id == UUID(chip_message_id)
            ).first()
            if chip_message:
                chip_message.deleted_at = datetime.now(timezone.utc)
                db.commit()
                logger.info(f"Marked chip payment message as deleted: {chip_message_id}")
            else:
                logger.warning(f"Chip message not found for chip_message_id: {chip_message_id}")
        except Exception as e:
            logger.error(f"Failed to delete chip message {chip_message_id}: {e}")
    return

########################################################
# 継続決済関連処理
########################################################

def _handle_recurring_payment(
    db: Session,
    transaction_id: Optional[str],
    status: Optional[str],
    amount: Optional[str],
) -> None:
    """Albatal継続決済の処理"""
    if status == ALBATAL_APPROVED_STATUS:
        payment = _handle_recurring_payment_success(
            db,
            transaction_id,
            status,
            amount,
        )

        if payment:
            _handle_payment_success_notification(db, payment)
    else:
        _handle_recurring_payment_failure(
            db,
            transaction_id,
        )
    return


def _handle_recurring_payment_success(
    db: Session,
    transaction_id: Optional[str],
    status: Optional[str],
    amount: Optional[str],
) -> Optional[Payments]:
    """Albatal継続決済完了通知の処理"""
    payment_transaction = payment_transactions_crud.get_transaction_by_id(db, transaction_id)
    if not payment_transaction:
        logger.error(f"Payment transaction not found: {transaction_id}")
        return

    # アクティブ中のサブスクリプションをキャンセル
    # トランザクションIDから最新のpaymentを取得
    payment = payments_crud.get_payment_by_transaction_id(db, transaction_id)
    if not payment:
        logger.error(f"Payment not found: {transaction_id}")
        return

    # サブスクリプションをキャンセル
    subscription = subscriptions_crud.update_subscription_status_by_payment_id(
        db,
        payment.id,
        SubscriptionStatus.EXPIRED,
        None,
        False,
        None,
    )

    # クリエイターのプラットフォーム手数料を更新
    creator = creator_crud.get_creator_by_user_id(db, payment.seller_user_id)
    if not creator:
        logger.error(f"Creator not found: {payment.seller_user_id}")
        return

    # サブスクリプションレコードを作成
    next_billing_date = datetime.now(timezone.utc) + timedelta(days=SUBSCRIPTION_DURATION_DAYS)

    # 決済レコードを作成
    new_payment = _create_payment_record(
        db,
        payment.order_id,
        payment_transaction.session_id,
        PaymentStatus.SUCCEEDED,
        payment.transaction_id,
        PaymentType.PLAN,
        ItemType.PLAN,
        payment.provider_id,
        payment.buyer_user_id,
        payment.seller_user_id,
        payment.payment_amount,
        payment.payment_price,
        creator.platform_fee_percent,
        datetime.now(timezone.utc),
    )

    _create_subscription_record(
        db,
        payment.buyer_user_id,
        SubscriptionStatus.ACTIVE,
        SubscriptionType.PLAN,
        payment.seller_user_id,
        payment.order_id,
        ItemType.PLAN,
        subscription.access_start,
        next_billing_date,
        payment.provider_id,
        new_payment.id,
        next_billing_date,
    )

    return payment

def _handle_recurring_payment_failure(
    db: Session,
    transaction_id: Optional[str],
) -> None:
    """Albatal継続決済失敗通知の処理"""
    payment_transaction = payment_transactions_crud.get_transaction_by_id(db, transaction_id)
    if not payment_transaction:
        logger.error(f"Payment transaction not found: {transaction_id}")
        return

    # アクティブ中のサブスクリプションをキャンセル
    # トランザクションIDから最新のpaymentを取得
    payment = payments_crud.get_payment_by_transaction_id(db, transaction_id)
    if not payment:
        logger.error(f"Payment not found: {transaction_id}")
        return

    # サブスクリプションをキャンセル
    subscriptions_crud.update_subscription_status_by_payment_id(
        db,
        payment.id,
        SubscriptionStatus.EXPIRED,
        None,
        True,
        canceled_at=datetime.now(timezone.utc),
    )

    # プラン情報を取得
    plan, creator = _get_subscription_seller_info(db, payment_transaction.order_id)
    if not plan or not creator:
        logger.error(f"Plan or creator not found: {payment_transaction.order_id}")
        return

    creator_info = user_crud.get_user_by_id(db, creator.user_id)
    if not creator_info:
        logger.error(f"Creator info not found: {creator.user_id}")
        return

    buyer_user = user_crud.get_user_by_id(db, payment_transaction.user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {payment_transaction.user_id}")
        return

    slack_alert._alert_subscription_expired(
        buyer_user.id,
        buyer_user.profile_name,
        plan.name,
        creator_info.profile_name,
        f"{os.environ.get('FRONTEND_URL', 'https://mijfans.jp/')}/plan/{plan.id}",
    )

    # 購入者の通知
    if CommonFunction.get_user_need_to_send_notification(
        db, payment_transaction.user_id, NotificationType.PAYMENTS
    ):
        _handle_buyer_subscription_payment_failure_notification(
            db, payment_transaction.user_id, payment_transaction
        )
    return

########################################################
# ユーザープロバイダー関連処理
########################################################

def _handle_update_creator_user_provider(
    db: Session,
    buyer_user_id: Optional[UUID],
    consumer_id: Optional[str],
    provider_id: Optional[UUID],
) -> None:
    """ユーザープロバイダーを作成または更新"""
    user_provider = user_providers_crud.get_user_provider(
        db=db,
        user_id=buyer_user_id,
        provider_id=provider_id
    )
    if not user_provider:
        logger.info(f"Creating user provider: {buyer_user_id}, {provider_id}, {consumer_id}")
        user_provider = user_providers_crud.create_user_provider(
            db=db,
            user_id=buyer_user_id,
            provider_id=provider_id,
            sendid=consumer_id,
            cardbrand=None,
            cardnumber=None,
            yuko=None,
            main_card=True,
        )
    else:
        user_provider.last_used_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user_provider)
    return

########################################################
# 通知関連処理
########################################################

def _send_chip_payment_success_notification(
    db: Session,
    payment: Optional[Payments],
) -> None:
    """Albatal投げ銭決済完了通知を送信"""
    if not payment:
        logger.error("Payment not found")
        return

    buyer_user_id = payment.buyer_user_id
    recipient_user_id = payment.seller_user_id

    # 購入者への通知
    if CommonFunction.get_user_need_to_send_notification(
        db, buyer_user_id, NotificationType.PAYMENTS
    ):
        _handle_buyer_chip_payment_success_notification(
            db, buyer_user_id, recipient_user_id, payment
        )

    # 売り手への通知
    if CommonFunction.get_user_need_to_send_notification(
        db, recipient_user_id, NotificationType.PAYMENTS
    ):
        _handle_seller_chip_payment_success_notification(
            db, buyer_user_id, recipient_user_id, payment
        )

def _handle_buyer_chip_payment_success_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    recipient_user_id: Optional[UUID],
    payment: Optional[Payments],
) -> None:
    """Albatal投げ銭決済完了通知を送信（購入者向け）"""
    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    recipient_user = user_crud.get_user_by_id(db, recipient_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {recipient_user_id}")
        return

    recipient_name = recipient_user.profile_name or "クリエイター"
    payment_date = _convert_utc_to_jst(payment.paid_at)

    # 会話IDを取得
    order_id_parts = payment.order_id.split("_") if payment.order_id else []
    chip_message_id = order_id_parts[1] if len(order_id_parts) > 1 else None
    conversation_id = _get_conversation_id_from_chip_message(db, chip_message_id)

    notification_redirect_url = (
        f"/message/conversation/{conversation_id}" if conversation_id else "/account/sale"
    )
    conversation_url = (
        f"{FRONTEND_URL}/message/conversation/{conversation_id}" if conversation_id else ""
    )

    title = f"{recipient_name}にチップ送信が完了しました"
    subtitle = title

    # メール送信
    try:
        send_chip_payment_buyer_success_email(
            to=buyer_user.email,
            recipient_name=recipient_name,
            conversation_url=conversation_url,
            transaction_id=str(payment.transaction_id),
            payment_amount=payment.payment_amount,
            payment_date=payment_date,
        )
    except Exception as e:
        logger.error(f"Failed to send chip payment buyer email: {e}")

    # 通知を追加
    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": DEFAULT_AVATAR_URL,
        "redirect_url": notification_redirect_url,
    }

    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": payment.buyer_user_id,
            "type": NotificationType.USERS,
            "payload": payload,
        },
    )

def _handle_seller_chip_payment_success_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    recipient_user_id: Optional[UUID],
    payment: Optional[Payments],
) -> None:
    """Albatal投げ銭決済完了通知を送信（売り手向け）"""
    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    recipient_user = user_crud.get_user_by_id(db, recipient_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {recipient_user_id}")
        return

    # チップ金額と売上金額を計算
    payment_amount = payment.payment_amount or 0
    chip_amount = _calculate_chip_amount_from_payment(payment_amount)

    creator_info = creator_crud.get_creator_by_user_id(db, recipient_user_id)
    if not creator_info:
        logger.error(f"Creator info not found: {recipient_user_id}")
        return

    seller_amount = _calculate_seller_amount(chip_amount, creator_info.platform_fee_percent)
    payment_date = _convert_utc_to_jst(payment.paid_at)
    buyer_name = buyer_user.profile_name or "ユーザー"

    # 会話IDを取得
    order_id_parts = payment.order_id.split("_") if payment.order_id else []
    chip_message_id = order_id_parts[1] if len(order_id_parts) > 1 else None
    conversation_id = _get_conversation_id_from_chip_message(db, chip_message_id)

    notification_redirect_url = (
        f"/message/conversation/{conversation_id}" if conversation_id else "/account/sale"
    )
    conversation_url = (
        f"{FRONTEND_URL}/message/conversation/{conversation_id}" if conversation_id else ""
    )
    sales_url = f"{FRONTEND_URL}/account/sale"

    title = f"{buyer_name}さんからチップが届きました"
    subtitle = title
    avatar_url = _get_user_avatar_url(buyer_user)

    # メール送信
    try:
        send_chip_payment_seller_success_email(
            to=recipient_user.email,
            sender_name=buyer_name,
            conversation_url=conversation_url,
            transaction_id=str(payment.transaction_id),
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

    notifications_crud.add_notification_for_selling_info(
        db=db,
        notification={
            "user_id": payment.seller_user_id,
            "type": NotificationType.PAYMENTS,
            "payload": payload,
        },
    )

def _handle_payment_success_notification(
    db: Session,
    payment: Optional[Payments],
) -> None:
    """Albatal決済完了通知を送信"""
    if not payment:
        logger.error("Payment not found")
        return

    buyer_user_id = payment.buyer_user_id
    recipient_user_id = payment.seller_user_id

    # 購入者への通知
    if CommonFunction.get_user_need_to_send_notification(
        db, buyer_user_id, NotificationType.PAYMENTS
    ):
        _handle_buyer_payment_success_notification(
            db, buyer_user_id, recipient_user_id, payment
        )

    # 売り手への通知
    if CommonFunction.get_user_need_to_send_notification(
        db, recipient_user_id, NotificationType.PAYMENTS
    ):
        _handle_seller_payment_success_notification(
            db, buyer_user_id, recipient_user_id, payment
        )

def _handle_payment_failure_notification(
    db: Session,
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """Albatal決済失敗通知を送信"""


    transaction_type = payment_transaction.type
    # 購入者への通知
    if CommonFunction.get_user_need_to_send_notification(
        db, payment_transaction.user_id, NotificationType.PAYMENTS
    ):
        if transaction_type in [PaymentTransactionType.SINGLE, PaymentTransactionType.SUBSCRIPTION]:
            _handle_buyer_payment_failure_notification(
                db, payment_transaction.user_id, payment_transaction
            )
        elif transaction_type == PaymentTransactionType.CHIP:
            _handle_buyer_chip_payment_failure_notification(
                db, payment_transaction.user_id, payment_transaction
            )


def _handle_buyer_payment_success_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    recipient_user_id: Optional[UUID],
    payment: Optional[Payments],
) -> None:
    """Albatal決済完了通知を送信（購入者向け・ルーティング）"""
    transaction_type = payment.payment_type
    if transaction_type == PaymentType.SINGLE:
        _handle_buyer_single_payment_success_notification(
            db, buyer_user_id, recipient_user_id, payment
        )
    elif transaction_type == PaymentType.PLAN:
        _handle_buyer_subscription_payment_success_notification(
            db, buyer_user_id, recipient_user_id, payment
        )
    else:
        logger.error(f"Invalid transaction type: {transaction_type}")

def _handle_buyer_single_payment_success_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    recipient_user_id: Optional[UUID],
    payment: Optional[Payments],
) -> None:
    """Albatal決済完了通知を送信（購入者向け・単発決済）"""
    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    # コンテンツ情報を取得
    price, post, creator = _get_single_seller_info(db, payment.order_id)
    if not price or not post or not creator:
        logger.error(f"Price or post or creator not found: {payment.order_id}")
        return

    contents_name = post.description
    notification_redirect_url = f"/post/detail?post_id={post.id}"
    payment_date = _convert_utc_to_jst(payment.paid_at)

    title = "決済が完了しました"
    subtitle = title

    # 通知を追加
    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": DEFAULT_AVATAR_URL,
        "redirect_url": notification_redirect_url,
    }

    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": payment.buyer_user_id,
            "type": NotificationType.USERS,
            "payload": payload,
        },
    )

    # メール送信
    try:
        email_content_url = f"{FRONTEND_URL}{notification_redirect_url}"
        send_payment_succuces_email(
            to=buyer_user.email,
            content_url=email_content_url,
            transaction_id=str(payment.transaction_id),
            contents_name=contents_name,
            payment_date=payment_date,
            amount=payment.payment_amount,
            sendid=payment.transaction_id,
            user_name=buyer_user.profile_name,
            user_email=buyer_user.email,
            purchase_history_url=f"{FRONTEND_URL}/bought/post",
        )
    except Exception as e:
        logger.error(f"Failed to send payment success email: {e}")

def _handle_buyer_subscription_payment_success_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    recipient_user_id: Optional[UUID],
    payment: Optional[Payments],
) -> None:
    """Albatal決済完了通知を送信（購入者向け・サブスクリプション）"""
    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    # コンテンツ情報を取得
    plan, creator = _get_subscription_seller_info(db, payment.order_id)
    if not plan or not creator:
        logger.error(f"Plan or creator not found: {payment.order_id}")
        return

    contents_name = plan.name
    notification_redirect_url = f"/plan/{plan.id}"
    payment_date = _convert_utc_to_jst(payment.paid_at)

    title = "決済が完了しました"
    subtitle = title

    # 通知を追加
    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": DEFAULT_AVATAR_URL,
        "redirect_url": notification_redirect_url,
    }

    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": buyer_user_id,
            "type": NotificationType.USERS,
            "payload": payload,
        },
    )

    # メール送信
    try:
        email_content_url = f"{FRONTEND_URL}{notification_redirect_url}"
        purchase_history_url = f"{FRONTEND_URL}/bought/post"
        send_payment_succuces_email(
            to=buyer_user.email,
            content_url=email_content_url,
            transaction_id=str(payment.transaction_id),
            contents_name=contents_name,
            payment_date=payment_date,
            amount=payment.payment_amount,
            sendid=payment.transaction_id,
            user_name=buyer_user.profile_name,
            user_email=buyer_user.email,
            purchase_history_url=purchase_history_url,
        )
    except Exception as e:
        logger.error(f"Failed to send payment success email: {e}")

def _handle_seller_single_payment_success_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    recipient_user_id: Optional[UUID],
    payment: Optional[Payments],
) -> None:
    """Albatal決済完了通知を送信（売り手向け・単発決済）"""
    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    recipient_user = user_crud.get_user_by_id(db, recipient_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {recipient_user_id}")
        return

    # コンテンツ情報を取得
    price, post, creator = _get_single_seller_info(db, payment.order_id)
    if not price or not post or not creator:
        logger.error(f"Price or post or creator not found: {payment.order_id}")
        return

    contents_name = post.description
    buyer_name = buyer_user.profile_name or "ユーザー"
    title = f"{buyer_name}さんが{contents_name}を購入しました"
    subtitle = title

    # 通知を追加
    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": _get_user_avatar_url(buyer_user),
        "redirect_url": "/account/sale",
    }

    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": recipient_user_id,
            "type": NotificationType.PAYMENTS,
            "payload": payload,
        },
    )

    # メール送信
    try:
        content_url = f"{FRONTEND_URL}/post/detail?post_id={post.id}"
        send_selling_info_email(
            to=recipient_user.email,
            buyer_name=buyer_name,
            contents_name=contents_name,
            seller_name=recipient_user.profile_name,
            content_url=content_url,
            contents_type=PaymentType.SINGLE,
            dashboard_url=f"{FRONTEND_URL}/account/sale",
        )
    except Exception as e:
        logger.error(f"Failed to send payment success email: {e}")

def _handle_seller_subscription_payment_success_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    recipient_user_id: Optional[UUID],
    payment: Optional[Payments],
) -> None:
    """Albatal決済完了通知を送信（売り手向け・サブスクリプション）"""
    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    recipient_user = user_crud.get_user_by_id(db, recipient_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {recipient_user_id}")
        return

    # コンテンツ情報を取得
    plan, creator = _get_subscription_seller_info(db, payment.order_id)
    if not plan or not creator:
        logger.error(f"Plan or creator not found: {payment.order_id}")
        return

    contents_name = plan.name
    buyer_name = buyer_user.profile_name or "ユーザー"
    title = f"{buyer_name}さんが{contents_name}プランに加入しました"
    subtitle = title

    # 通知を追加
    payload = {
        "title": title,
        "subtitle": subtitle,
        "avatar": _get_user_avatar_url(buyer_user),
        "redirect_url": "/account/sale",
    }

    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": recipient_user_id,
            "type": NotificationType.PAYMENTS,
            "payload": payload,
        },
    )

    # メール送信
    try:
        content_url = f"{FRONTEND_URL}/plan/{plan.id}"
        send_selling_info_email(
            to=recipient_user.email,
            buyer_name=buyer_name,
            contents_name=contents_name,
            seller_name=recipient_user.profile_name,
            content_url=content_url,
            contents_type=PaymentType.PLAN,
            dashboard_url=f"{FRONTEND_URL}/account/sale",
        )
    except Exception as e:
        logger.error(f"Failed to send payment success email: {e}")

def _handle_seller_payment_success_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    recipient_user_id: Optional[UUID],
    payment: Optional[Payments],
) -> None:
    """Albatal決済完了通知を送信（売り手向け・ルーティング）"""
    transaction_type = payment.payment_type
    if transaction_type == PaymentType.SINGLE:
        _handle_seller_single_payment_success_notification(
            db, buyer_user_id, recipient_user_id, payment
        )
    elif transaction_type == PaymentType.PLAN:
        _handle_seller_subscription_payment_success_notification(
            db, buyer_user_id, recipient_user_id, payment
        )
    else:
        logger.error(f"Invalid transaction type: {transaction_type}")

def _handle_buyer_payment_failure_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """Albatal決済失敗通知を送信（購入者向け）"""
    if not buyer_user_id or not payment_transaction:
        logger.error(f"Buyer user id or payment transaction not found: {buyer_user_id} or {payment_transaction}")
        return

    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    payment_date = _convert_utc_to_jst(payment_transaction.updated_at)
    send_payment_faild_email(
        to=buyer_user.email,
        transaction_id=str(payment_transaction.id),
        failure_date=payment_date,
        sendid=payment_transaction.id,
        user_name=buyer_user.profile_name,
        user_email=buyer_user.email,
    )
    return      

def _handle_buyer_subscription_payment_failure_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """Albatal決済失敗通知を送信（購入者向け・サブスクリプション）"""
    if not buyer_user_id or not payment_transaction:
        logger.error(f"Buyer user id or payment transaction not found: {buyer_user_id} or {payment_transaction}")
        return

    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    plan, creator = _get_subscription_seller_info(db, payment_transaction.order_id)
    if not plan or not creator:
        logger.error(f"Plan or creator not found: {payment_transaction.order_id}")
        return

    creator_info = user_crud.get_user_by_id(db, creator.user_id)
    if not creator_info:
        logger.error(f"Creator info not found: {creator.user_id}")
        return

    contents_name = plan.name
    email_content_url = f"{FRONTEND_URL}/plan/{plan.id}"

    payload = {
        "title": f"{contents_name}プランの決済に失敗したため、プランが解約されました",
        "subtitle": f"{contents_name}プランの決済に失敗したため、プランが解約されました",
        "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
        "redirect_url": email_content_url,
    }

    send_buyer_cancel_subscription_email(
        to=buyer_user.email,
        user_name=buyer_user.profile_name,
        creator_user_name=creator_info.profile_name,
        plan_name=contents_name,
        plan_url=email_content_url,
    )

     # プラン解約の通知
    notifications_crud.add_notification_for_cancel_subscription(
        db=db,
        notification={
            "user_id": buyer_user.id,
            "type": NotificationType.USERS,
            "payload": payload,
        },
    )
    return

def _handle_buyer_chip_payment_failure_notification(
    db: Session,
    buyer_user_id: Optional[UUID],
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """Albatal決済失敗通知を送信（購入者向け・投げ銭）"""

    if not buyer_user_id or not payment_transaction:
        logger.error(f"Buyer user id or payment transaction not found: {buyer_user_id} or {payment_transaction}")
        return

    buyer_user = user_crud.get_user_by_id(db, buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {buyer_user_id}")
        return

    order_id_parts = payment_transaction.order_id.split("_")
    chip_message_id = order_id_parts[1] if len(order_id_parts) > 1 else None
    conversation_id = _get_conversation_id_from_chip_message(db, chip_message_id)
    if not conversation_id:
        logger.error(f"Conversation id not found: {payment_transaction.order_id}")
        return

    title = "チップの送信に失敗しました"
    subtitle = "チップの送信に失敗しました"
    notification_redirect_url = f"/message/conversation/{conversation_id}" if conversation_id else "/account/sale"

    # 失敗時のメール送信
    send_payment_faild_email(
        to=buyer_user.email,
        transaction_id=str(payment_transaction.id),
        failure_date=_convert_utc_to_jst(payment_transaction.updated_at),
        sendid=payment_transaction.id,
        user_name=buyer_user.profile_name,
        user_email=buyer_user.email,
    )

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
            "user_id": buyer_user.id,
            "type": NotificationType.USERS,
            "payload": payload,
        },
    )
    return

########################################################
# データ取得関連処理
########################################################
def _get_single_seller_info(
    db: Session,
    order_id: Optional[str],
) -> Tuple[Optional[Prices], Optional[Posts], Optional[Creators]]:
    """Single決済の売り上げ情報（price, post, creator）を取得"""
    price, post, creator = price_crud.get_price_and_post_by_id(db, order_id)
    if not price or not post or not creator:
        logger.error(f"Price or post or creator not found: {order_id}")
        return None, None, None
    return price, post, creator

def _get_subscription_seller_info(
    db: Session,
    order_id: Optional[str],
) -> Tuple[Optional[Plans], Optional[Creators]]:
    """
    Subscription決済の売り上げ情報（seller_user_id, platform_fee_percent）を取得
    """
    plan, creator = plan_crud.get_plan_and_creator_by_id(db, order_id)
    if not plan or not creator:
        logger.error(f"Plan or creator not found: {order_id}")
        return None, None
    return plan, creator

def _create_payment_record(
    db: Session,
    order_id: Optional[str],
    provide_payment_id: Optional[str],
    status: Optional[int],
    transaction_id: Optional[UUID],
    payment_type: Optional[int],
    order_type: Optional[int],
    provider_id: Optional[UUID],
    buyer_user_id: Optional[UUID],
    seller_user_id: Optional[UUID],
    payment_amount: Optional[int],
    payment_price: Optional[int],
    platform_fee: Optional[int],
    paid_at: Optional[datetime],
) -> Optional[Payments]:
    """Payment recordを作成"""
    return payments_crud.create_payment(
        db=db,
        transaction_id=transaction_id,
        payment_type=payment_type,
        order_id=order_id,
        order_type=order_type,
        provider_id=provider_id,
        provider_payment_id=provide_payment_id,
        buyer_user_id=buyer_user_id,
        seller_user_id=seller_user_id,
        payment_amount=payment_amount,
        payment_price=payment_price,
        status=status,
        platform_fee=platform_fee,
        paid_at=paid_at,
    )

def _create_subscription_record(
    db: Session,
    user_id: Optional[UUID],
    status: Optional[int],
    access_type: Optional[int],
    creator_id: Optional[UUID],
    order_id: Optional[str],
    order_type: Optional[int],
    access_start: Optional[datetime],
    access_end: Optional[datetime],
    provider_id: Optional[UUID],
    payment_id: Optional[UUID],
    next_billing_date: Optional[datetime] = None,
) -> None:
    """Subscription recordを作成"""
    subscriptions_crud.create_subscription(
        db=db,
        access_type=access_type,
        user_id=user_id,
        creator_id=creator_id,
        order_id=order_id,
        order_type=order_type,
        access_start=access_start,
        access_end=access_end,
        next_billing_date=next_billing_date,
        provider_id=provider_id,
        payment_id=payment_id,
        status=status,
    )