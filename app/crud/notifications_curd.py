from datetime import datetime, timezone
from typing import List
from typing import Optional
from uuid import UUID
from sqlalchemy import asc, desc, func, or_, update, cast as sa_cast
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.models import Users
from app.models.notifications import Notifications
from app.schemas.notification import NotificationCreateRequest, NotificationType
from app.core.logger import Logger

logger = Logger.get_logger()


def get_notifications_admin_paginated(
    db: Session,
    page: int = 1,
    limit: int = 20,
    search: Optional[str] = None,
    sort: str = "created_at_desc",
) -> tuple[List[Notifications], int]:
    """
    管理者用の通知一覧を取得

    Args:
      db: データベースセッション
      page: ページ番号
      limit: 1ページあたりの件数
      search: 検索クエリ
      sort: ソート順

    Returns:
      tuple[List[Notifications], int]: (通知リスト, 総件数)
    """
    skip = (page - 1) * limit
    query = db.query(Notifications).filter(Notifications.type == NotificationType.ADMIN)
    if search:
        query = query.filter(Notifications.payload["title"].astext.ilike(f"%{search}%"))
    if sort:
        if sort == "created_at_desc":
            query = query.order_by(desc(Notifications.created_at))
        elif sort == "created_at_asc":
            query = query.order_by(asc(Notifications.created_at))
    total = query.count()
    notifications = query.offset(skip).limit(limit).all()
    return notifications, total


def create_notification_admin(
    db: Session, notification: NotificationCreateRequest
) -> Notifications:
    """
    管理者用の通知を作成
    """
    try:
        new_notification = Notifications(
            type=notification.type,
            payload=notification.payload,
            is_read=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(new_notification)
        db.commit()
        return new_notification
    except Exception as e:
        logger.error(f"Create notification error: {e}")
        db.rollback()
        return None


def update_notification_admin(
    db: Session, notification_id: UUID, notification_update: NotificationCreateRequest
) -> Notifications:
    """
    管理者用の通知を更新
    """
    try:
        update_fields = {
            "title": notification_update.payload["title"],
            "subtitle": notification_update.payload["subtitle"],
            "message": notification_update.payload["message"],
        }
        update_values = {
            "updated_at": datetime.now(timezone.utc),
        }
        if update_fields:
            pairs: list[object] = []
            for k, v in update_fields.items():
                pairs.extend([k, v])
            jsonb_obj = func.jsonb_build_object(*pairs)
            # payload = payload || jsonb_build_object(...)
            update_values["payload"] = Notifications.payload.op("||")(jsonb_obj)

        exec = (
            update(Notifications)
            .where(Notifications.id == notification_id)
            .values(**update_values)
            .returning(Notifications)
        )
        result = db.execute(exec)
        notification = result.scalars().first()
        if not notification:
            db.rollback()
            return None
        db.commit()
        return notification
    except Exception as e:
        logger.error(f"Update notification error: {e}")
        db.rollback()
        return None


def get_notifications_paginated(
    db: Session, user: Users, type: NotificationType, page: int = 1, limit: int = 20
) -> tuple[List[Notifications], int]:
    """
    通知をページングで取得
    """
    try:
        skip = (page - 1) * limit
        if type == NotificationType.ADMIN:
            query = (
                db.query(Notifications)
                .filter(
                    or_(
                        Notifications.user_id == user.id,
                        Notifications.user_id.is_(None),
                    ),
                    Notifications.type == type,
                    Notifications.created_at >= user.created_at,
                )
                .order_by(desc(Notifications.created_at))
            )
        elif type == NotificationType.USERS:
            query = (
                db.query(Notifications)
                .filter(
                    Notifications.user_id == user.id,
                    Notifications.type == type,
                    Notifications.created_at >= user.created_at,
                )
                .order_by(desc(Notifications.created_at))
            )
        elif type == NotificationType.PAYMENTS:
            query = (
                db.query(Notifications)
                .filter(
                    Notifications.user_id == user.id,
                    Notifications.type == type,
                    Notifications.created_at >= user.created_at,
                )
                .order_by(desc(Notifications.created_at))
            )
        elif type == NotificationType.ALL:
            query = (
                db.query(Notifications)
                .filter(
                    or_(
                        Notifications.user_id == user.id,
                        Notifications.user_id.is_(None),
                    ),
                    Notifications.created_at >= user.created_at,
                    Notifications.type.in_(
                        [
                            NotificationType.ADMIN,
                            NotificationType.USERS,
                            NotificationType.PAYMENTS,
                        ]
                    ),
                )
                .order_by(desc(Notifications.created_at))
            )
        total = query.count()
        notifications = query.offset(skip).limit(limit).all()
        has_next = (skip + limit) < total
        return notifications, total, has_next
    except Exception as e:
        logger.error(f"Get notifications paginated error: {e}")
        return [], 0, False


def mark_notification_as_read(
    db: Session, notification_id: UUID, user_id: UUID, type: NotificationType
) -> Notifications:
    """
    通知を既読にする
    """
    try:
        if type == NotificationType.ADMIN:
            return __mark_notification_as_read_admin(db, notification_id, user_id)
        elif type == NotificationType.USERS:
            return __mark_notification_as_read_users(db, notification_id, user_id)
        elif type == NotificationType.PAYMENTS:
            return __mark_notification_as_read_payments(db, notification_id, user_id)
        else:
            return None

    except Exception as e:
        logger.error(f"Mark notification as read error: {e}")
        return None


def __mark_notification_as_read_admin(
    db: Session, notification_id: UUID, user_id: UUID
) -> bool:
    """
    管理者用の通知を既読にする
    """
    payload_col = Notifications.payload

    users_array_expr = func.coalesce(payload_col["users"], func.cast("[]", JSONB)).op(
        "||"
    )(func.jsonb_build_array(str(user_id)))

    stmt = (
        update(Notifications)
        .where(Notifications.id == notification_id)
        .values(
            payload=func.jsonb_set(
                payload_col,
                "{users}",
                users_array_expr,
            ),
            updated_at=datetime.now(timezone.utc),
        )
        .returning(Notifications)
    )

    try:
        result = db.execute(stmt)
        notification = result.scalars().first()
        if not notification:
            db.rollback()
            return None
        db.commit()
        return notification
    except Exception as e:
        logger.error(f"Mark notification as read error: {e}")
        db.rollback()
        return None


def __mark_notification_as_read_users(
    db: Session, notification_id: UUID, user_id: UUID
) -> bool:
    """
    users -> users の通知を既読にする
    """

    try:
        exec = (
            update(Notifications)
            .where(Notifications.id == notification_id)
            .values(
                is_read=True,
                read_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(Notifications)
        )
        result = db.execute(exec)
        notification = result.scalars().first()
        if not notification:
            db.rollback()
            return None
        db.commit()
        return notification
    except Exception as e:
        logger.error(f"Mark notification as read users error: {e}")
        db.rollback()
        return None


def __mark_notification_as_read_payments(
    db: Session, notification_id: UUID, user_id: UUID
) -> bool:
    """
    payments -> users の通知を既読にする
    """

    try:
        exec = (
            update(Notifications)
            .where(Notifications.id == notification_id)
            .values(
                is_read=True,
                read_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(Notifications)
        )
        result = db.execute(exec)
        notification = result.scalars().first()
        if not notification:
            db.rollback()
            return None
        db.commit()
        return notification
    except Exception as e:
        logger.error(f"Mark notification as read payments error: {e}")
        db.rollback()
        return None


def get_unread_count(db: Session, user: Users) -> int:
    """
    未読通知数を取得
    """
    try:
        user_str = str(user.id)

        cond_has_user = __has_user_expr(user_str)

        admin_count = (
            db.query(func.count(Notifications.id))
            .filter(
                Notifications.type == NotificationType.ADMIN,
                Notifications.created_at >= user.created_at,
                ~cond_has_user,
            )
            .scalar()
        )
        users_count = (
            db.query(Notifications)
            .filter(
                Notifications.type == NotificationType.USERS,
                Notifications.user_id == user.id,
                Notifications.created_at >= user.created_at,
                Notifications.is_read == False,
            )
            .count()
        )
        payments_count = (
            db.query(Notifications)
            .filter(
                Notifications.type == NotificationType.PAYMENTS,
                Notifications.user_id == user.id,
                Notifications.created_at >= user.created_at,
                Notifications.is_read == False,
            )
            .count()
        )
        return admin_count, users_count, payments_count
    except Exception as e:
        logger.error(f"Get unread count error: {e}")
        return 0, 0, 0


def __has_user_expr(user_id: str):
    users_array = func.coalesce(
        Notifications.payload["users"],
        sa_cast("[]", JSONB),
    )
    return users_array.op("?")(user_id)
