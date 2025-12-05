from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.crud.subscriptions_crud import cancel_subscription
from app.core.logger import Logger
from app.deps.auth import get_current_user
from app.models.user import Users

logger = Logger.get_logger()
router = APIRouter()

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
        return {
            "result": True,
            "next_billing_date": result.next_billing_date
        }
    except Exception as e:
        db.rollback()
        logger.error(f"サブスクリプションキャンセルエラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))