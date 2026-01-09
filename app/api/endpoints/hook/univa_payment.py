"""
Univapay決済Webhookエンドポイント
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from fastapi.responses import PlainTextResponse
from uuid import UUID
from typing import Optional, Tuple
from app.core.logger import Logger
import json
import re
import os
from datetime import datetime, timedelta, timezone
from app.api.commons.function import CommonFunction
from app.models.payments import Payments
from app.models.payment_transactions import PaymentTransactions
from app.models.subscriptions import Subscriptions
from app.models.conversation_messages import ConversationMessages
from app.constants.enums import (
    PaymentType, 
    PaymentStatus, 
    PaymentTransactionStatus, 
    ConversationMessageStatus, 
    SubscriptionType, 
    ItemType, 
    SubscriptionStatus,
)
from app.schemas.notification import NotificationType
from app.crud.payment_transactions_crud import create_payment_transaction
from app.crud.providers_crud import get_provider_by_code
from app.crud import user_crud, profile_crud, notifications_crud, creator_crud
from app.crud.user_crud import get_user_by_id
from app.crud.payments_crud import get_payment_by_session_id
from app.crud.conversations_crud import get_or_create_dm_conversation, create_chip_message
from app.crud.price_crud import get_price_and_post_by_id
from app.crud.creator_crud import get_creator_by_user_id
from app.crud.payment_transactions_crud import get_transaction_by_session_id, update_transaction_status
from app.crud.payments_crud import create_payment, update_payment_status_by_transaction_id
from app.crud.subscriptions_crud import create_subscription
from app.services.email.send_email import (
    send_chip_payment_buyer_success_email,
    send_chip_payment_seller_success_email,
    send_payment_faild_email,
    send_payment_succuces_email,
    send_selling_info_email,
)

logger = Logger.get_logger()
router = APIRouter()

# 定数
MAPPING_PAYMENT_TYPE = {
    "chip": PaymentType.CHIP,
    "single": PaymentType.SINGLE,
}

UNIVA_PROVIDER_CODE = "univapay"
RESULT_OK = "ok"
RESULT_NG = "ng"
CDN_BASE_URL = os.environ.get("CDN_BASE_URL")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://mijfans.jp")
DEFAULT_AVATAR_URL = "https://logo.mijfans.jp/bimi/logo.svg"
JST_TIMEZONE = timezone(timedelta(hours=9))

# ステータス定数
STATUS_SUCCESSFUL = "successful"
STATUS_FAILED = "failed"
STATUS_ERRORED = "errored"
FAILED_STATUSES = [STATUS_FAILED, STATUS_ERRORED]

# 通知タイプ定数
NOTIFICATION_TYPE_USER_PAYMENTS = "userPayments"
NOTIFICATION_TYPE_CREATOR_PAYMENTS = "creatorPayments"


class ChargeFinishedPayload:
    """successful charge_finished webhook payload"""

    def __init__(self, data: dict):
        self.id = data.get("id")
        self.store_id = data.get("store_id")
        self.transaction_token_id = data.get("transaction_token_id")
        self.event = data.get("event")
        self.data = data.get("data", {})
        self.requested_amount = data.get("requested_amount")
        self.charged_amount = data.get("charged_amount")
        self.status = data.get("status")
        self.error = data.get("error")
        self.metadata = data.get("metadata", {})
        self.created_on = data.get("created_on")
        self.successful = data.get("successful", False)


# ==================== ヘルパー関数 ====================

def _convert_utc_to_jst(dt: datetime) -> datetime:
    """UTC時刻をJSTに変換"""
    if dt.tzinfo is None:
        utc_time = dt.replace(tzinfo=timezone.utc)
    else:
        utc_time = dt
    return utc_time.astimezone(JST_TIMEZONE)


def _format_datetime_jst(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """UTC時刻をJSTに変換してフォーマット"""
    jst_time = _convert_utc_to_jst(dt)
    return jst_time.strftime(format_str)


def _calculate_payment_price_from_amount(payment_amount: int) -> int:
    """決済金額から商品価格を計算（税込から税抜）"""
    return (payment_amount * 100 + 110 - 1) // 110


def _get_transaction_by_session_id(db: Session, session_id: str) -> Optional[PaymentTransactions]:
    """セッションIDからトランザクションを取得"""
    transaction = get_transaction_by_session_id(db, session_id)
    if not transaction:
        logger.warning(f"Transaction not found: {session_id}")
    return transaction


def _get_payment_by_transaction_id(db: Session, transaction_id: UUID) -> Optional[Payments]:
    """トランザクションIDからpaymentを取得"""
    payment = get_payment_by_session_id(db, transaction_id)
    if not payment:
        logger.warning(f"Payment not found: {transaction_id}")
    return payment


def _get_transaction_and_payment(
    db: Session, session_id: str
) -> Optional[Tuple[PaymentTransactions, Payments]]:
    """セッションIDからトランザクションとpaymentを取得"""
    transaction = _get_transaction_by_session_id(db, session_id)
    if not transaction:
        return None
    
    payment = _get_payment_by_transaction_id(db, transaction.id)
    if not payment:
        return None
    
    return transaction, payment

def _get_provider(db: Session) -> Optional:
    """Univapayプロバイダーを取得"""
    provider = get_provider_by_code(db, UNIVA_PROVIDER_CODE)
    if not provider:
        logger.error("Provider not found")
    return provider


def _calculate_payment_due_date(data: dict) -> Optional[datetime]:
    """
    expiration_periodとexpiration_time_shiftから決済期限日時を計算
    
    Args:
        data: charge.data オブジェクト
        
    Returns:
        計算された決済期限日時、もしくはNone
    """
    try:
        data_obj = data.get("data", {})
        expiration_period = data_obj.get("expiration_period")
        expiration_time_shift = data_obj.get("expiration_time_shift")
        
        if not expiration_period or not expiration_time_shift:
            logger.warning("expiration_period or expiration_time_shift not found in data")
            return None
        
        # expiration_period (例: "PT168H") から時間数を抽出
        period_match = re.search(r'PT(\d+)H', expiration_period)
        if not period_match:
            logger.warning(f"Invalid expiration_period format: {expiration_period}")
            return None
        
        hours = int(period_match.group(1))
        now = datetime.now(timezone.utc)
        due_date = now + timedelta(hours=hours)
        
        # expiration_time_shift (例: "23:59:59+09:00") から時刻とタイムゾーンを取得
        time_shift_match = re.match(r'(\d{2}):(\d{2}):(\d{2})([+-])(\d{2}):(\d{2})', expiration_time_shift)
        if not time_shift_match:
            logger.warning(f"Invalid expiration_time_shift format: {expiration_time_shift}")
            return None
        
        hour = int(time_shift_match.group(1))
        minute = int(time_shift_match.group(2))
        second = int(time_shift_match.group(3))
        tz_sign = time_shift_match.group(4)
        tz_hour_offset = int(time_shift_match.group(5))
        tz_minute_offset = int(time_shift_match.group(6))
        
        tz_offset_minutes = tz_hour_offset * 60 + tz_minute_offset
        if tz_sign == '-':
            tz_offset_minutes = -tz_offset_minutes
        
        tz = timezone(timedelta(minutes=tz_offset_minutes))
        due_date_in_tz = due_date.astimezone(tz)
        due_date_with_time = due_date_in_tz.replace(
            hour=hour, minute=minute, second=second, microsecond=0
        )
        
        return due_date_with_time.astimezone(timezone.utc)
        
    except Exception as e:
        logger.error(f"Error calculating payment_due_date: {e}")
        return None


def _get_payment_user_info(metadata: dict, payment_type: int) -> Tuple[Optional[str], Optional[str]]:
    """payment_typeに応じてuser_idとorder_idを取得"""
    if payment_type == PaymentType.CHIP:
        user_id = metadata.get("payment_user_id")
        order_id = f"{metadata.get('payment_user_id')}_{metadata.get('recipient_user_id')}"
    elif payment_type == PaymentType.SINGLE:
        user_id = metadata.get("user_id")
        order_id = metadata.get("product_code")
    else:
        return None, None
    return user_id, order_id


def _get_buyer_seller_info(
    db: Session, metadata: dict, payment_type: int
) -> Optional[Tuple[UUID, UUID, int]]:
    """buyer_user_id, seller_user_id, platform_feeを取得"""
    if payment_type == PaymentType.CHIP:
        seller_user_id = metadata.get('recipient_user_id')
        buyer_user_id = metadata.get("payment_user_id")
        creator = get_creator_by_user_id(db, seller_user_id)
        if not creator:
            logger.warning(f"Creator not found: {seller_user_id}")
            return None
        platform_fee = creator.platform_fee_percent
    elif payment_type == PaymentType.SINGLE:
        buyer_user_id = metadata.get("user_id")
        price, post, creator = get_price_and_post_by_id(db, metadata.get("product_code"))
        if not price or not post or not creator:
            logger.warning(f"Price not found: {metadata.get('product_code')}")
            return None
        seller_user_id = post.creator_user_id
        platform_fee = creator.platform_fee_percent
    else:
        return None
    
    return buyer_user_id, seller_user_id, platform_fee


# ==================== Webhookエンドポイント ====================

@router.post("/payment")
async def univa_payment_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Univa payment webhook endpoint

    Args:
        request (Request): ユニバペイの決済完了webhookリクエスト
        db (Session): データベースセッション

    Returns:
        PlainTextResponse: 成功時はsuccess、エラー時はerror
    """
    try:
        body = await request.body()
        payload = json.loads(body)

        logger.info(f"Univa payment webhook payload: {payload}")

        charge = ChargeFinishedPayload(payload)

        event_handlers = {
            'token_created': _handle_token_created,
            'charge_updated': _handle_charge_updated,
            'charge_finished': _handle_charge_finished,
        }
        handler = event_handlers.get(charge.event)
        if handler:
            handler(charge, db)
        
        return PlainTextResponse(content="success", status_code=200)
        
    except Exception as e:
        logger.error(f"Error parsing JSON: {e}")
        return PlainTextResponse(status_code=200, content="error")


# ==================== イベントハンドラー ====================

def _handle_token_created(charge: ChargeFinishedPayload, db: Session) -> None:
    """Handle token_created event from Univapay"""
    logger.info(f"Token created: {charge.data}")

    provider = _get_provider(db)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    metadata = charge.data.get("metadata", {})
    payment_type = MAPPING_PAYMENT_TYPE.get(metadata.get("payment_type"))
    if not payment_type:
        logger.warning(f"Unknown payment type: {metadata.get('payment_type')}")
        return
    
    user_id, order_id = _get_payment_user_info(metadata, payment_type)
    if not user_id or not order_id:
        logger.warning(f"Invalid user_id or order_id for payment_type: {payment_type}")
        return
    
    payment_due_date = _calculate_payment_due_date(charge.data)
    
    create_payment_transaction(
        db, 
        user_id, 
        provider.id, 
        payment_type, 
        metadata.get("session_id"), 
        order_id,
        payment_due_date=payment_due_date
    )


def _handle_charge_updated(charge: ChargeFinishedPayload, db: Session) -> None:
    """Handle charge updated event from Univapay"""
    logger.info(f"Charge updated: {charge.data}")

    provider = _get_provider(db)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    metadata = charge.data.get("metadata", {})
    payment_type = MAPPING_PAYMENT_TYPE.get(metadata.get("payment_type"))
    if not payment_type:
        logger.warning(f"Unknown payment type: {metadata.get('payment_type')}")
        return

    session_id = metadata.get("session_id")
    transaction = _get_transaction_by_session_id(db, session_id)
    if not transaction:
        return
    
    buyer_seller_info = _get_buyer_seller_info(db, metadata, payment_type)
    if not buyer_seller_info:
        return
    
    buyer_user_id, seller_user_id, platform_fee = buyer_seller_info

    charged_amount = charge.data.get("charged_amount")
    if not charged_amount:
        logger.warning("charged_amount not found in charge data")
        return
    
    payment_amount = charged_amount
    payment_price = _calculate_payment_price_from_amount(payment_amount)

    _create_payment(
        db=db,
        transaction=transaction,
        payment_type=payment_type,
        order_id=transaction.order_id,
        order_type=payment_type,
        provider_id=provider.id,
        provider_payment_id=session_id,
        buyer_user_id=buyer_user_id,
        seller_user_id=seller_user_id,
        payment_amount=payment_amount,
        payment_price=payment_price,
        status=PaymentStatus.PENDING,
        platform_fee=platform_fee,
    )


def _handle_charge_finished(charge: ChargeFinishedPayload, db: Session) -> None:
    """Handle charge finished event from Univapay"""
    logger.info(f"Charge finished: {charge.data}")

    metadata = charge.data.get("metadata", {})
    payment_type = MAPPING_PAYMENT_TYPE.get(metadata.get("payment_type"))
    status = charge.data.get("status")

    if not payment_type:
        logger.warning(f"Unknown payment type: {metadata.get('payment_type')}")
        return

    if payment_type == PaymentType.CHIP:
        if status == STATUS_SUCCESSFUL:
            _handle_chip_payment_success(charge, db)
        elif status in FAILED_STATUSES:
            _handle_chip_payment_failure(charge, db)
        else:
            logger.warning(f"Unknown status: {status}")
    elif payment_type == PaymentType.SINGLE:
        if status == STATUS_SUCCESSFUL:
            _handle_single_payment_success(charge, db)
        elif status in FAILED_STATUSES:
            _handle_single_payment_failure(charge, db)
        else:
            logger.warning(f"Unknown status: {status}")


# ==================== 決済成功/失敗ハンドラー ====================

def _handle_chip_payment_success(charge: ChargeFinishedPayload, db: Session) -> None:
    """Handle chip payment success event from Univapay"""
    logger.info(f"Chip payment success: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    transaction = _get_transaction_by_session_id(db, session_id)
    if not transaction:
        return
    
    payment_amount = charge.data.get("charged_amount")
    if not payment_amount:
        logger.warning("payment_amount not found in charge data")
        return
    
    payment_price = _calculate_payment_price_from_amount(payment_amount)
    
    payment = _update_payment_status(
        db, 
        transaction.id,
        PaymentStatus.SUCCEEDED,
        payment_amount,
        payment_price,
        paid_at=datetime.now(timezone.utc),
    )

    _update_transaction_status(db, transaction.id, PaymentTransactionStatus.COMPLETED)

    buyer_user_info = get_user_by_id(db, payment.buyer_user_id)
    if not buyer_user_info:
        logger.error(f"Buyer user not found: {payment.buyer_user_id}")
        return

    # チップメッセージを作成
    message_text = metadata.get("message")
    if message_text:
        chip_message = f"{buyer_user_info.profile_name}さんが{payment.payment_price}円のチップを送りました！\n\n【メッセージ】\n{message_text}"
    else:
        chip_message = f"{buyer_user_info.profile_name}さんが{payment.payment_price}円のチップを送りました！"

    conversation = get_or_create_dm_conversation(
        db, 
        user_id_1=payment.buyer_user_id,
        user_id_2=payment.seller_user_id,
    )

    create_chip_message(
        db, 
        conversation.id,
        sender_user_id=payment.buyer_user_id,
        body_text=chip_message,
        status=ConversationMessageStatus.ACTIVE,
    )

    # 通知送信
    _send_notifications_if_needed(
        db, payment.buyer_user_id, payment.seller_user_id,
        lambda: _handle_chip_payment_notification_for_buyer(charge, db, conversation.id),
        lambda: _handle_chip_payment_notification_for_seller(charge, db, conversation.id),
    )


def _handle_chip_payment_failure(charge: ChargeFinishedPayload, db: Session) -> None:
    """Handle chip payment failure event from Univapay"""
    logger.info(f"Chip payment failure: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    transaction = _get_transaction_by_session_id(db, session_id)
    if not transaction:
        return
    
    _update_transaction_status(db, transaction.id, PaymentTransactionStatus.FAILED)

    _update_payment_status(
        db, 
        transaction.id, 
        PaymentStatus.FAILED, 
        payment_amount=0, 
        payment_price=0, 
        paid_at=None,
    )


def _handle_single_payment_success(charge: ChargeFinishedPayload, db: Session) -> None:
    """Handle single payment success event from Univapay"""
    logger.info(f"Single payment success: {charge.data}")
    
    provider = _get_provider(db)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    transaction = _get_transaction_by_session_id(db, session_id)
    if not transaction:
        return
    
    payment_amount = charge.data.get("charged_amount")
    if not payment_amount:
        logger.warning("payment_amount not found in charge data")
        return
    
    payment_price = _calculate_payment_price_from_amount(payment_amount)
    
    payment = _update_payment_status(
        db, 
        transaction.id,
        PaymentStatus.SUCCEEDED,
        payment_amount,
        payment_price,
        paid_at=datetime.now(timezone.utc),
    )

    _update_transaction_status(db, transaction.id, PaymentTransactionStatus.COMPLETED)

    _create_subscription(
        db, 
        transaction, 
        payment, 
        buyer_user_id=payment.buyer_user_id,
        seller_user_id=payment.seller_user_id,
        provider_id=provider.id,
    )

    # 通知送信
    _send_notifications_if_needed(
        db, payment.buyer_user_id, payment.seller_user_id,
        lambda: _handle_single_payment_notification_for_buyer(charge, db),
        lambda: _handle_single_payment_notification_for_seller(charge, db),
    )


def _handle_single_payment_failure(charge: ChargeFinishedPayload, db: Session) -> None:
    """Handle single payment failure event from Univapay"""
    logger.info(f"Single payment failure: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    transaction = _get_transaction_by_session_id(db, session_id)
    if not transaction:
        return
    
    _update_transaction_status(db, transaction.id, PaymentTransactionStatus.FAILED)

    _update_payment_status(
        db, 
        transaction.id, 
        PaymentStatus.FAILED, 
        payment_amount=0, 
        payment_price=0, 
        paid_at=datetime.now(timezone.utc),
    )


# ==================== 通知ハンドラー ====================

def _send_notifications_if_needed(
    db: Session,
    buyer_user_id: UUID,
    seller_user_id: UUID,
    buyer_notification_func,
    seller_notification_func,
) -> None:
    """通知設定を確認して通知を送信"""
    if CommonFunction.get_user_need_to_send_notification(db, buyer_user_id, NOTIFICATION_TYPE_USER_PAYMENTS):
        buyer_notification_func()
    
    if CommonFunction.get_user_need_to_send_notification(db, seller_user_id, NOTIFICATION_TYPE_CREATOR_PAYMENTS):
        seller_notification_func()


def _handle_chip_payment_notification_for_buyer(
    charge: ChargeFinishedPayload, db: Session, conversation_id: UUID
) -> None:
    """Handle chip payment notification for buyer event from Univapay"""
    logger.info(f"Chip payment notification for buyer: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    result = _get_transaction_and_payment(db, session_id)
    if not result:
        return
    
    transaction, payment = result

    buyer_user = get_user_by_id(db, payment.buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {payment.buyer_user_id}")
        return
    
    recipient_user = get_user_by_id(db, payment.seller_user_id)
    recipient_name = recipient_user.profile_name if recipient_user else "クリエイター"
    
    payment_amount = payment.payment_amount or 0
    payment_date = _format_datetime_jst(transaction.updated_at)
    
    title = f"{recipient_name}にチップ送信が完了しました"
    notification_redirect_url = f"/message/conversation/{conversation_id}" if conversation_id else "/account/sale"
    
    try:
        send_chip_payment_buyer_success_email(
            to=buyer_user.email,
            recipient_name=recipient_name,
            conversation_url=f"{FRONTEND_URL}/message/conversation/{conversation_id}",
            transaction_id=str(transaction.id),
            payment_amount=payment_amount,
            payment_date=payment_date,
            payment_type="bank_payment",
        )
    except Exception as e:
        logger.error(f"Failed to send chip payment buyer email: {e}")
    
    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": payment.buyer_user_id,
            "type": NotificationType.USERS,
            "payload": {
                "title": title,
                "subtitle": title,
                "avatar": DEFAULT_AVATAR_URL,
                "redirect_url": notification_redirect_url,
            },
        },
    )


def _handle_chip_payment_notification_for_seller(
    charge: ChargeFinishedPayload, db: Session, conversation_id: UUID
) -> None:
    """Handle chip payment notification for seller event from Univapay"""
    logger.info(f"Chip payment notification for seller: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    result = _get_transaction_and_payment(db, session_id)
    if not result:
        return
    
    transaction, payment = result
    
    recipient_user = get_user_by_id(db, payment.seller_user_id)
    if not recipient_user:
        logger.error(f"Recipient user not found: {payment.seller_user_id}")
        return
    
    buyer_user = get_user_by_id(db, transaction.user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {transaction.user_id}")
        return
    
    buyer_profile = profile_crud.get_profile_by_user_id(db, transaction.user_id)
    buyer_name = buyer_user.profile_name if buyer_user else "ユーザー"
    
    # payment_priceからplatform_feeを差し引いた金額をseller_amountに設定
    # 例: payment_price=1000円, platform_fee=10%の場合、seller_amount=900円
    fee_per_payment = (payment.payment_price * payment.platform_fee) // 100
    seller_amount = payment.payment_price - fee_per_payment
    
    payment_date = _format_datetime_jst(transaction.updated_at, "%Y年%m月%d日 %H:%M")
    title = f"{buyer_name}さんからチップが届きました"
    
    avatar_url = DEFAULT_AVATAR_URL
    if buyer_profile and buyer_profile.avatar_url:
        avatar_url = f"{CDN_BASE_URL}/{buyer_profile.avatar_url}"
    
    try:
        send_chip_payment_seller_success_email(
            to=recipient_user.email,
            sender_name=buyer_name,
            conversation_url=f"{FRONTEND_URL}/message/conversation/{conversation_id}",
            transaction_id=str(transaction.id),
            seller_amount=seller_amount,
            payment_date=payment_date,
            sales_url=f"{FRONTEND_URL}/account/sale",
        )
    except Exception as e:
        logger.error(f"Failed to send chip payment seller email: {e}")
    
    notifications_crud.add_notification_for_selling_info(
        db=db,
        notification={
            "user_id": UUID(recipient_user_id),
            "type": NotificationType.PAYMENTS,
            "payload": {
                "title": title,
                "subtitle": title,
                "avatar": avatar_url,
                "redirect_url": f"{FRONTEND_URL}/message/conversation/{conversation_id}",
            },
        },
    )


def _handle_chip_payment_failure_notification_for_buyer(
    charge: ChargeFinishedPayload, db: Session
) -> None:
    """Handle chip payment failure notification for buyer event from Univapay"""
    logger.info(f"Chip payment failure notification for buyer: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    result = _get_transaction_and_payment(db, session_id)
    if not result:
        return
    
    transaction, payment = result
    
    buyer_user = get_user_by_id(db, payment.buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {payment.buyer_user_id}")
        return
    
    payment_date = _format_datetime_jst(transaction.updated_at)
    title = "チップの送信に失敗しました"

    notifications_crud.add_notification_for_selling_info(
        db=db,
        notification={
            "user_id": payment.buyer_user_id,
            "type": NotificationType.USERS,
            "payload": {
                "title": title,
                "subtitle": title,
                "avatar": DEFAULT_AVATAR_URL,
            },
        },
    )

    try:
        send_payment_faild_email(
            to=buyer_user.email,
            transaction_id=str(transaction.id),
            failure_date=payment_date,
            sendid=transaction.session_id,
            user_name=buyer_user.profile_name,
            user_email=buyer_user.email,
        )
    except Exception as e:
        logger.error(f"Failed to send chip payment failure notification for buyer: {e}")


def _handle_single_payment_notification_for_buyer(
    charge: ChargeFinishedPayload, db: Session
) -> None:
    """Handle single payment notification for buyer event from Univapay"""
    logger.info(f"Single payment notification for buyer: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    result = _get_transaction_and_payment(db, session_id)
    if not result:
        return
    
    transaction, payment = result

    buyer_user = get_user_by_id(db, payment.buyer_user_id)
    if not buyer_user:
        logger.error(f"Buyer user not found: {payment.buyer_user_id}")
        return
    
    price, post, creator = get_price_and_post_by_id(db, metadata.get("product_code"))
    if not price or not post or not creator:
        logger.warning(f"Price not found: {metadata.get('product_code')}")
        return
    
    contents_name = post.description
    payment_date = _format_datetime_jst(transaction.updated_at)
    payment_amount = payment.payment_amount or 0

    notification_redirect_url = f"/post/detail?post_id={post.id}"
    email_content_url = f"{FRONTEND_URL}{notification_redirect_url}"

    try:
        send_payment_succuces_email(
            to=buyer_user.email,
            content_url=email_content_url,
            transaction_id=str(transaction.id),
            contents_name=contents_name,
            payment_date=payment_date,
            amount=payment_amount,
            sendid=transaction.session_id,
            user_name=buyer_user.profile_name,
            user_email=buyer_user.email,
            purchase_history_url=f"{FRONTEND_URL}/bought/post",
            payment_type="bank_payment",
        )
    except Exception as e:
        logger.error(f"Failed to send single payment notification for buyer: {e}")
    
    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": payment.buyer_user_id,
            "type": NotificationType.USERS,
            "payload": {
                "title": "決済が完了しました",
                "subtitle": "決済が完了しました",
                "avatar": DEFAULT_AVATAR_URL,
                "redirect_url": notification_redirect_url,
            },
        },
    )


def _handle_single_payment_notification_for_seller(
    charge: ChargeFinishedPayload, db: Session
) -> None:
    """Handle single payment notification for seller event from Univapay"""
    logger.info(f"Single payment notification for seller: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    result = _get_transaction_and_payment(db, session_id)
    if not result:
        return
    
    transaction, payment = result
    
    seller_user = get_user_by_id(db, payment.seller_user_id)
    if not seller_user:
        logger.error(f"Seller user not found: {payment.seller_user_id}")
        return

    buyer_user = get_user_by_id(db, payment.buyer_user_id)
    buyer_name = buyer_user.profile_name if buyer_user else "ユーザー"

    price, post, creator = get_price_and_post_by_id(db, metadata.get("product_code"))
    if not price or not post or not creator:
        logger.warning(f"Price not found: {metadata.get('product_code')}")
        return
    
    contents_name = post.description
    title = f"{buyer_name}さんが{contents_name}を購入しました"

    avatar_url = DEFAULT_AVATAR_URL
    if buyer_user and buyer_user.profile and buyer_user.profile.avatar_url:
        avatar_url = f"{CDN_BASE_URL}/{buyer_user.profile.avatar_url}"
    
    notifications_crud.add_notification_for_payment_succuces(
        db=db,
        notification={
            "user_id": payment.seller_user_id,
            "type": NotificationType.USERS,
            "payload": {
                "title": title,
                "subtitle": title,
                "avatar": avatar_url,
                "redirect_url": "/account/sale",
            },
        },
    )
    
    try:
        send_selling_info_email(
            to=seller_user.email,
            buyer_name=buyer_name,
            contents_name=contents_name,
            seller_name=seller_user.profile_name,
            content_url=f"{FRONTEND_URL}/post/detail?post_id={post.id}",
            contents_type=PaymentType.SINGLE,
            dashboard_url=f"{FRONTEND_URL}/account/sale",
        )
    except Exception as e:
        logger.error(f"Failed to send single payment notification for seller: {e}")


def _handle_single_payment_failure_notification_for_buyer(
    charge: ChargeFinishedPayload, db: Session
) -> None:
    """Handle single payment failure notification for buyer event from Univapay"""
    logger.info(f"Single payment failure notification for buyer: {charge.data}")
    
    metadata = charge.data.get("metadata", {})
    session_id = metadata.get("session_id")
    result = _get_transaction_and_payment(db, session_id)
    if not result:
        return
    
    transaction, payment = result
    
    seller_user = get_user_by_id(db, payment.seller_user_id)
    if not seller_user:
        logger.error(f"Seller user not found: {payment.seller_user_id}")
        return
    
    payment_date = _format_datetime_jst(transaction.updated_at)
    title = "商品の購入に失敗しました"

    notifications_crud.add_notification_for_selling_info(
        db=db,
        notification={
            "user_id": payment.seller_user_id,
            "type": NotificationType.USERS,
            "payload": {
                "title": title,
                "subtitle": title,
                "avatar": DEFAULT_AVATAR_URL,
            },
        },
    )

    try:
        send_payment_faild_email(
            to=seller_user.email,
            transaction_id=str(transaction.id),
            failure_date=payment_date,
            sendid=transaction.session_id,
            user_name=seller_user.profile_name,
            user_email=seller_user.email,
        )
    except Exception as e:
        logger.error(f"Failed to send single payment failure notification for buyer: {e}")


# ==================== データベース操作ヘルパー ====================

def _create_payment(
    db: Session,
    transaction: PaymentTransactions,
    payment_type: int,
    order_id: str,
    order_type: int,
    provider_id: UUID,
    provider_payment_id: str,
    buyer_user_id: UUID,
    seller_user_id: UUID,
    payment_amount: int,
    payment_price: int,
    status: int,
    platform_fee: int,
) -> Payments:
    """Create payment record"""
    return create_payment(
        db=db,
        transaction_id=transaction.id,
        payment_type=payment_type,
        order_id=order_id,
        order_type=order_type,
        provider_id=provider_id,
        provider_payment_id=provider_payment_id,
        buyer_user_id=buyer_user_id,
        seller_user_id=seller_user_id,
        payment_amount=payment_amount,
        payment_price=payment_price,
        status=status,
        platform_fee=platform_fee,
        paid_at=None,
    )


def _create_subscription(
    db: Session, 
    transaction: PaymentTransactions, 
    payment: Payments, 
    buyer_user_id: UUID, 
    seller_user_id: UUID,
    provider_id: UUID,
) -> Subscriptions:
    """Create subscription record"""
    return create_subscription(
        db=db,
        access_type=SubscriptionType.SINGLE,
        user_id=buyer_user_id,
        creator_id=seller_user_id,
        order_id=transaction.order_id,
        order_type=ItemType.POST,
        access_start=datetime.now(timezone.utc),
        access_end=None,
        next_billing_date=None,
        provider_id=provider_id,
        payment_id=payment.id,
        status=SubscriptionStatus.ACTIVE,
    )


def _update_payment_status(
    db: Session,
    transaction_id: UUID,
    status: int,
    payment_amount: int,
    payment_price: int,
    paid_at: datetime = None,
) -> Payments:
    """Update payment status"""
    return update_payment_status_by_transaction_id(
        db, 
        transaction_id, 
        status,
        payment_amount,
        payment_price,
        paid_at,
    )


def _update_transaction_status(
    db: Session, transaction_id: UUID, status: int
) -> PaymentTransactions:
    """Update transaction status"""
    return update_transaction_status(db, transaction_id, status)
