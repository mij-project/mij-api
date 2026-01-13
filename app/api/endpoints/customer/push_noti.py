from fastapi import APIRouter, Depends, HTTPException

from app.core.logger import Logger
from app.schemas.push_noti import SubscribePushNotificationRequest, UnsubscribePushNotificationRequest, UpdateSubscribePushNotificationRequest
from app.db.base import get_db
from sqlalchemy.orm import Session
from app.deps.auth import get_current_user
from app.models.user import Users
from app.crud.push_noti_crud import create_or_update_push_notification, unsubscribe_push_notification, update_subscribe_push_notification

logger = Logger.get_logger()
router = APIRouter()

@router.post("/subscribe")
async def subscribe_push_notification_for_user(
    payload: SubscribePushNotificationRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict:
    done  = create_or_update_push_notification(db, current_user.id, payload)
    if not done:
        raise HTTPException(status_code=500, detail="Failed to create or update push notification")
    return {"message": "Done"}

@router.post("/unsubscribe")
async def unsubscribe_push_notification_for_user(
    payload: UnsubscribePushNotificationRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict:
    unsubscribe_push_notification(db, current_user.id, payload)
    return {"message": "Done"}

@router.post("/update-subscribe")
async def update_subscribe_push_notification_for_user(
    payload: UpdateSubscribePushNotificationRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
) -> dict:
    update_subscribe_push_notification(db, current_user.id, payload)
    return {"message": "Done"}