from fastapi import APIRouter, Depends, Form, Response
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.constants.enums import (
    PaymentTransactionType,
    PaymentType,
    ItemType,
    SubscriptionStatus,
    SubscriptionType,
    PaymentTransactionStatus,
)
PaymentTransactionType, PaymentType, ItemType, SubscriptionStatus, SubscriptionType
from app.schemas.albatal import AlbatalWebhookPaymentNotification, AlbatalWebhookRecurringNotification
from typing import Optional
from app.core.logger import Logger
from app.crud import (
    payment_transactions_crud, 
    providers_crud, price_crud, 
    plan_crud, 
    payments_crud, 
    subscriptions_crud, 
    user_providers_crud, 
    user_crud, 
    conversations_crud, 
    plan_crud,time_sale_crud
)
from app.models.payment_transactions import PaymentTransactions
from app.constants.enums import PaymentStatus
from app.models.prices import Prices
from app.models.creators import Creators
from app.models.plans import Plans
from typing import Tuple
from datetime import datetime, timedelta
from uuid import UUID   
from datetime import timezone
logger = Logger.get_logger()
router = APIRouter()

ALBATAL_SUCCESS_RESPONSE = "successok"
ALBATAL_APPROVED_STATUS = "approved"


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
    """
    Albatalウェブフック通知受信ログを出力
    """
    logger.info(f"Albatal WPF決済完了通知受信: {wpf_transaction_id}")
    logger.info(f"Albatal WPF決済完了通知受信: {wpf_status}")
    logger.info(f"Albatal WPF決済完了通知受信: {wpf_unique_id}")
    logger.info(f"Albatal WPF決済通知受信: {payment_transaction_unique_id}")
    logger.info(f"Albatal WPF決済通知受信: {payment_transaction_amount}")
    logger.info(f"Albatal WPF決済通知受信: {consumer_id}")
    logger.info(f"Albatal WPF決済通知受信: {notification_type}")
    logger.info(f"Albatal WPF決済通知受信: {signature}")

def _log_recurring_webhook_received(
    transaction_id: Optional[str],
    unique_id: Optional[str],
    merchant_transaction_id: Optional[str],
    status: Optional[str],
    amount: Optional[str],
) -> None:
    """
    Albatal定期決済通知受信ログを出力
    """
    logger.info(f"Albatal定期決済通知受信: {transaction_id}")
    logger.info(f"Albatal定期決済通知受信: {unique_id}")
    logger.info(f"Albatal定期決済通知受信: {merchant_transaction_id}")
    logger.info(f"Albatal定期決済通知受信: {status}")
    logger.info(f"Albatal定期決済通知受信: {amount}")

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
        # WPF決済完了通知か定期決済通知かを判定
        if wpf_transaction_id:
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

           # 初回決済完了通知の場合
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
        else:
            _log_recurring_webhook_received(
                transaction_id,
                unique_id,
                merchant_transaction_id,
                status,
                amount,
            )
        
        logger.info(f"Albatalウェブフック通知処理完了🚀🚀🚀")
        return Response(content=ALBATAL_SUCCESS_RESPONSE, status_code=200)

    except Exception as e:
        logger.error(f"Albatalウェブフック処理エラー: {str(e)}", exc_info=True)
        # Albatalへのエラー応答はHTTP 200で返す（再送信を避けるため）
        return Response(content=ALBATAL_SUCCESS_RESPONSE, status_code=200)

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
        _handle_wpf_payment_success(
            db,
            wpf_unique_id,
            payment_transaction_amount,
            payment_transaction,
        )
    else:
        _handle_wpf_payment_failure(
            db,
            wpf_transaction_id,
            wpf_status,
            wpf_unique_id,
            payment_transaction_unique_id,
            payment_transaction_amount,
            consumer_id,

            payment_transaction,
        )
    return


def _handle_wpf_payment_success(
    db: Session,
    wpf_unique_id: Optional[str],
    payment_transaction_amount: Optional[str],
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """
    Albatal初回決済完了通知の処理
    """

    provider = providers_crud.get_provider_by_code(db, "albatal")

    # payment情報をセット
    buyer_user_id = payment_transaction.user_id
    seller_user_id = None
    platform_fee = None
    payment_amount = int(payment_transaction_amount)
    payment_price = (payment_amount * 100 + 110 - 1) // 110
    order_id = payment_transaction.order_id
    seller_user_id = None
    platform_fee = None
    payment_type = None
    order_type = None

    if payment_transaction.type == PaymentTransactionType.SINGLE:
        price, post, creator = _get_single_seller_info(db, payment_transaction.order_id)
        seller_user_id = post.creator_user_id
        platform_fee = creator.platform_fee_percent
        payment_type = PaymentType.SINGLE
        order_type = ItemType.POST
    elif payment_transaction.type == PaymentTransactionType.SUBSCRIPTION:
        plan, creator = _get_subscription_seller_info(db, payment_transaction.order_id)
        seller_user_id = plan.creator_user_id
        platform_fee = creator.platform_fee_percent
        payment_type = PaymentType.PLAN
        order_type = ItemType.PLAN
        _handle_plan_payment_success(db, plan, payment_transaction)
    else:
        logger.error(f"Invalid payment transaction type: {payment_transaction.type}")
        return
    
    payment = _create_payment_record(
        db,
        payment_transaction.order_id,
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
        return
    logger.info(f"Payment record created: {payment.id}")

    access_type = SubscriptionType.PLAN if payment_type == PaymentType.PLAN else SubscriptionType.SINGLE
    next_billing_date = None
    if payment_type == PaymentType.PLAN:
        next_billing_date = datetime.now(timezone.utc) + timedelta(days=30)

    _create_subscription_record(
        db,
        buyer_user_id,
        SubscriptionStatus.ACTIVE,
        access_type,
        seller_user_id,
        payment_transaction.order_id,
        order_type,
        datetime.now(timezone.utc),
        None,
        provider.id,
        payment.id,
        next_billing_date,
    )

    payment_transactions_crud.update_transaction_status(
        db,
        payment_transaction.id,
        PaymentTransactionStatus.COMPLETED,
    )

    user_providers_crud.update_user_provider_is_valid(
        db,
        buyer_user_id,
        True,
    )

    logger.info(f"Payment transaction status updated: {payment_transaction.id}")

    return



def _handle_plan_payment_success(
    db: Session,
    plan: Optional[Plans],
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """
    Albatal定期決済完了通知の処理
    """
    """プラン加入時のDMの通知を送信"""

    # welcome_messageがない場合は通知を送信しない
    if not plan or plan.welcome_message is None or plan.welcome_message == "":
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
            f"Sent welcome message: {message.id} from creator={creator_user_id} to buyer={buyer_user_id} in conversation={conversation.id}"
        )
    except Exception as e:
        logger.error(f"Failed to send DM notification: {e}", exc_info=True)
        # エラーが発生しても決済処理は継続するため、例外は握りつぶす
        return
    
def _handle_wpf_payment_failure(
    db: Session,
    wpf_transaction_id: Optional[str],
    wpf_status: Optional[str],
    wpf_unique_id: Optional[str],
    payment_transaction_unique_id: Optional[str],
    payment_transaction_amount: Optional[str],
    consumer_id: Optional[str],
    notification_type: Optional[str],
    signature: Optional[str],
    payment_transaction: Optional[PaymentTransactions],
) -> None:
    """
    Albatal初回決済失敗通知の処理
    """
    return


def _get_single_seller_info(
    db: Session,
    order_id: Optional[str],
) -> Tuple[Optional[Prices], Optional[Creators]]:
    """
    Single決済の売り上げ情報（seller_user_id, platform_fee_percent）を取得
    """
    price, post, creator = price_crud.get_price_and_post_by_id(db, order_id)
    if not price or not post or not creator:
        logger.error(f"Price or post or creator not found: {order_id}")
        return None, None
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
) -> None:
    """
    Payment recordを作成
    """
    payment = payments_crud.create_payment(
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
    return payment

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
    """
    Subscription recordを作成
    """
    subscription = subscriptions_crud.create_subscription(
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
    return subscription