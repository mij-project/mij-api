import json
import os
from sqlalchemy.orm import Session
from uuid import UUID
from app.schemas.push_noti import (
    SubscribePushNotificationRequest,
    UnsubscribePushNotificationRequest,
    UpdateSubscribePushNotificationRequest,
)
from app.models.push_notifications import PushNotifications
from datetime import datetime, timezone
from app.core.logger import Logger
from pywebpush import webpush, WebPushException


logger = Logger.get_logger()


def create_or_update_push_notification(
    db: Session, user_id: UUID, payload: SubscribePushNotificationRequest
) -> bool:
    try:
        now = datetime.now(timezone.utc)
        endpoint = str(payload.subscription.endpoint).strip()
        p256dh = payload.subscription.keys.p256dh
        auth = payload.subscription.keys.auth
        platform = payload.platform
        existing_subscription = (
            db.query(PushNotifications)
            .filter(PushNotifications.endpoint == endpoint)
            .one_or_none()
        )
        if existing_subscription and (
            str(existing_subscription.user_id) == str(user_id)
        ):
            existing_subscription.p256dh = p256dh
            existing_subscription.auth = auth
            existing_subscription.platform = platform
            existing_subscription.is_active = True
            existing_subscription.updated_at = now
            db.commit()
            db.refresh(existing_subscription)
            return True
        elif existing_subscription and (
            str(existing_subscription.user_id) == str(user_id)
        ):
            existing_subscription.user_id = user_id
            existing_subscription.p256dh = p256dh
            existing_subscription.auth = auth
            existing_subscription.platform = platform
            existing_subscription.is_active = True
            existing_subscription.updated_at = now
        else:
            new_subscription = PushNotifications(
                user_id=user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                platform=platform,
                is_active=True,
                updated_at=now,
            )
            db.add(new_subscription)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error subscribing to push notification: {e}")
        return False


def push_notification_to_user(db: Session, user_id: UUID, payload: dict) -> None:
    try:
        now = datetime.now(timezone.utc)
        title = payload.get("title", "")
        body = payload.get("body", "")
        url = payload.get("url", "https://mijfans.jp")
        push_notifications = (
            db.query(PushNotifications)
            .filter(PushNotifications.user_id == user_id)
            .filter(PushNotifications.is_active.is_(True))
            .all()
        )
        for push_notification in push_notifications:
            try:
                sub = {
                    "endpoint": push_notification.endpoint,
                    "keys": {
                        "p256dh": push_notification.p256dh,
                        "auth": push_notification.auth,
                    },
                }
                webpush(
                    subscription_info=sub,
                    data=json.dumps(
                        {
                            "title": title,
                            "body": body,
                            "url": url,
                        }
                    ),
                    vapid_private_key=os.environ.get("VAPID_PRIVATE_KEY"),
                    vapid_claims={
                        "sub": "mailto:support@mijfans.jp",
                    },
                )
            except WebPushException as e:
                logger.error(f"Error pushing notification to user: {e}")
                push_notification.is_active = False
                push_notification.updated_at = now
                db.flush()
                continue
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Error pushing notification to user: {e}")


def unsubscribe_push_notification(
    db: Session, user_id: UUID, payload: UnsubscribePushNotificationRequest
) -> None:
    try:
        endpoint = str(payload.subscription.endpoint).strip()
        push_notification = (
            db.query(PushNotifications)
            .filter(
                PushNotifications.endpoint == endpoint,
                PushNotifications.user_id == user_id,
            )
            .one_or_none()
        )
        if push_notification:
            push_notification.is_active = False
            push_notification.updated_at = datetime.now(timezone.utc)
            db.commit()
        return None
    except Exception as e:
        db.rollback()
        logger.error(f"Error unsubscribing push notification: {e}")
        return None


def update_subscribe_push_notification(
    db: Session, user_id: UUID, payload: UpdateSubscribePushNotificationRequest
) -> None:
    try:
        now = datetime.now(timezone.utc)
        endpoint = str(payload.subscription.endpoint).strip()
        push_notification = (
            db.query(PushNotifications)
            .filter(PushNotifications.endpoint == endpoint)
            .one_or_none()
        )
        if push_notification:
            push_notification.user_id = user_id
            push_notification.is_active = True
            push_notification.updated_at = now
            db.commit()
        return None
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating subscribe push notification: {e}")
        return None
