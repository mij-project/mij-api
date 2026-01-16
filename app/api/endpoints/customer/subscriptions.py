from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.crud.subscriptions_crud import cancel_subscription, create_free_subscription
from app.api.commons.function import CommonFunction
from app.crud.payments_crud import create_free_payment
from app.crud.plan_crud import get_plan_by_id
from app.crud.price_crud import get_price_and_post_by_id
from app.crud.user_crud import get_user_by_id
from app.crud.payments_crud import get_payment_by_id
from app.crud.notifications_crud import add_notification_for_cancel_subscription
from app.services.email.send_email import send_cancel_subscription_email
from app.core.logger import Logger
from app.deps.auth import get_current_user
from app.models.user import Users
from app.models.payments import Payments
from app.schemas.notification import NotificationType
from app.schemas.subscriptions import FreeSubscriptionRequest, FreeSubscriptionResponse
from app.constants.enums import PaymentTransactionType, SubscriptionType, ItemType, PaymentType
from uuid import UUID
from typing import Tuple
import os
import httpx

logger = Logger.get_logger()
router = APIRouter()

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://mijfans.jp")
BASE_URL = os.getenv("CDN_BASE_URL")
ALBATAL_API_KEY = os.getenv("ALBATAL_PAY_API_KEY", "")
ALBATAL_API_WPF_URL = os.getenv("ALBATAL_API_WPF_URL", "https://staging.console.albatal.ltd")
@router.put("/cancel/{plan_id}")
def update_cancel_subscription(
    plan_id: str, 
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    サブスクリプションをキャンセル
    """
    try:

        result = cancel_subscription(db, plan_id, current_user.id)

        if not result:
            raise HTTPException(status_code=404, detail="サブスクリプションが見つかりません")

        # プラン解約の通知を送信
        order_id = result.order_id
        cancel_user_id = result.user_id
        cancel_user = get_user_by_id(db, cancel_user_id)

        # プラン情報を取得
        plan = get_plan_by_id(db, order_id)
        if not plan:
            raise HTTPException(status_code=404, detail="プランが見つかりません")

        plan_name = plan.name
        creator_user_id = plan.creator_user_id
        creator_user = get_user_by_id(db, creator_user_id)
        if not creator_user:
            raise HTTPException(status_code=404, detail="クリエイターが見つかりません")
        
        creator_user_name = creator_user.profile_name
        creator_user_email = creator_user.email
        plan_url = f"{FRONTEND_URL}/plan/{plan.id}"


        # アルバタルペイメントの場合は、アルバタルサブスクリプション解約処理を行う

        payment, provider_code = get_payment_by_id(db, result.payment_id)
        if provider_code == "albatal":
            _handole_albatal_subscription_cancel(db, payment)

        if CommonFunction.get_user_need_to_send_notification(db, creator_user.id, str(NotificationType.PAYMENTS)):
            # プラン解約の通知を追加
            title = f"{current_user.profile_name}さんが{plan_name}プランを解約しました"
            subtitle = f"{current_user.profile_name}さんが{plan_name}プランを解約しました"

            payload = {
                "title": title,
                "subtitle": subtitle,
                "avatar": f"{BASE_URL}/{cancel_user.profile.avatar_url}" if cancel_user.profile.avatar_url else "https://logo.mijfans.jp/bimi/logo.svg",
                "redirect_url": f"/plan/{plan.id}",
            }

            notification = {
                "user_id": creator_user.id,
                "type": NotificationType.USERS,
                "payload": payload,
            }
            add_notification_for_cancel_subscription(db=db, notification=notification)

            # メール送信
            send_cancel_subscription_email(
                to=creator_user_email,
                user_name=current_user.profile_name,
                creator_user_name=creator_user_name,
                plan_name=plan_name,
                plan_url=plan_url,
            )

        return {
            "result": True,
            "next_billing_date": result.next_billing_date
        }

    except Exception as e:
        db.rollback()
        logger.error("サブスクリプションキャンセルエラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/free", response_model=FreeSubscriptionResponse)
def create_free_subscription_endpoint(
    request_data: FreeSubscriptionRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    0円プラン・商品への加入処理
    - paymentsテーブルにレコード作成
    - subscriptionsテーブルにレコード作成（無期限）
    - プラン加入時はクリエイターに通知とメール送信
    """
    try:
        # purchase_typeに基づいて処理を分岐
        is_plan = request_data.purchase_type == PaymentTransactionType.SUBSCRIPTION

        if is_plan:
            # プランの場合
            plan = get_plan_by_id(db, UUID(request_data.order_id))
            if not plan:
                raise HTTPException(status_code=404, detail="プランが見つかりません")

            if plan.price != 0:
                raise HTTPException(status_code=400, detail="このプランは0円ではありません")

            seller_user_id = plan.creator_user_id
            payment_price = plan.price
            access_type = SubscriptionType.PLAN
            order_type = ItemType.PLAN
            payment_type = PaymentType.PLAN
            content_name = plan.name
            content_url = f"{FRONTEND_URL}/plan/{plan.id}"
        else:
            # 単品購入の場合
            price, post, creator = get_price_and_post_by_id(db, UUID(request_data.order_id))
            if not price or not post:
                raise HTTPException(status_code=404, detail="商品が見つかりません")

            if price.price != 0:
                raise HTTPException(status_code=400, detail="この商品は0円ではありません")

            seller_user_id = post.creator_user_id
            payment_price = price.price
            access_type = SubscriptionType.SINGLE
            order_type = ItemType.POST
            payment_type = PaymentType.SINGLE
            content_name = post.description or "投稿"
            content_url = f"{FRONTEND_URL}/post/detail?post_id={post.id}"

        # 1. paymentsテーブルにレコード作成
        payment = create_free_payment(
            db=db,
            payment_type=payment_type,
            order_id=request_data.order_id,
            order_type=order_type,
            buyer_user_id=current_user.id,
            seller_user_id=seller_user_id,
            payment_price=payment_price,
            platform_fee=0,
        )

        # 2. subscriptionsテーブルにレコード作成（無期限）
        subscription = create_free_subscription(
            db=db,
            access_type=access_type,
            user_id=current_user.id,
            creator_id=seller_user_id,
            order_id=request_data.order_id,
            order_type=order_type,
            payment_id=payment.id,
        )

        db.commit()

        return FreeSubscriptionResponse(
            result=True,
            subscription_id=subscription.id,
            message="加入が完了しました"
        )

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("0円プラン・商品加入エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


def _handole_albatal_subscription_cancel(db: Session, payment: Payments):
    """
    Albatalサブスクリプション解約処理

    Albatal Managed Recurring アイテムをキャンセルします。
    エラーが発生した場合はログして続行します。

    Args:
        db: データベースセッション
        payment: 決済レコード
    """
    try:
        # transaction_idが存在するかチェック
        if not payment.transaction_id:
            logger.warning(f"Payment {payment.id} has no transaction_id")
            return

        # 削除エンドポイントURLを構成
        # ALBATAL_API_WPF_URL: https://staging.console.albatal.ltd/api/wpf/create
        # 削除API: DELETE /api/wpf/managed_recurring/items/{transaction_id}
        delete_url = f"{ALBATAL_API_WPF_URL}/api/wpf/managed_recurring/items/{payment.transaction_id}"

        # Albatal APIへDELETEリクエストを送信
        with httpx.Client() as client:
            response = client.delete(
                delete_url,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {ALBATAL_API_KEY}",
                },
                timeout=30.0,
            )

        # ステータスコードをチェック
        if response.status_code == 200:
            logger.info(f"Successfully cancelled Albatal managed recurring item for payment {payment.id}")
        else:
            # エラーが発生した場合はログして続行
            error_message = f"Failed to cancel Albatal managed recurring item. Status: {response.status_code}, Response: {response.text}"
            logger.warning(f"Payment {payment.id}: {error_message}")

    except Exception as e:
        # 予期しないエラーが発生した場合もログして続行
        logger.error(f"Error cancelling Albatal subscription for payment {payment.id}: {str(e)}")