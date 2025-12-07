from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.crud.subscriptions_crud import cancel_subscription
from app.crud.plan_crud import get_plan_by_id
from app.crud.user_crud import get_user_by_id
from app.crud.notifications_crud import add_notification_for_cancel_subscription
from app.services.email.send_email import send_cancel_subscription_email
from app.core.logger import Logger
from app.deps.auth import get_current_user
from app.models.user import Users
from app.schemas.notification import NotificationType
import os

logger = Logger.get_logger()
router = APIRouter()

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://mijfans.jp")
BASE_URL = os.getenv("CDN_BASE_URL")
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


        # TODO: メール設定を行う
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