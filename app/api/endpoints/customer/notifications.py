from ast import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.crud.notifications_curd import (
  get_notifications_paginated, 
  mark_notification_as_read as mark_notification_as_read_crud, 
  get_unread_count as get_unread_count_crud
)
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.schemas.notification import GetUnreadCountResponse, MarkNotificationAsReadRequest, NotificationCreateResponse, NotificationType, PaginatedNotificationUserResponse


router = APIRouter()

@router.get("", response_model=PaginatedNotificationUserResponse)
async def get_notifications(
    type: NotificationType = Query(..., description='通知種別: 1: admin -> users 2: users -> users 3: payments'),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """
    通知を取得

    Args:
        type: 通知種別: 1: admin -> users 2: users -> users 3: payments
        page: ページ番号
        limit: 1ページあたりの件数

    Returns:
        NotificationUserResponse: 通知リスト
    """
    notifications, total, has_next = get_notifications_paginated(db, current_user.id, type, page, limit)

    return PaginatedNotificationUserResponse(
        notifications=[NotificationCreateResponse(
          id=notification.id,
          type=notification.type,
          payload=notification.payload,
          is_read=notification.is_read,
          read_at=notification.read_at,
          created_at=notification.created_at,
          updated_at=notification.updated_at
        ) for notification in notifications],
        total=total,
        page=page,
        total_pages=total // limit,
        has_next=has_next
    )

@router.patch("/read")
async def mark_notification_as_read(
    request: MarkNotificationAsReadRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    通知を既読にする
    """
    notification_as_read = mark_notification_as_read_crud(db, request.notification_id, request.user_id, request.type)
    if not notification_as_read:
        raise HTTPException(status_code=500, detail="Failed to mark notification as read")
    return {"status": "success", "message": "Notification marked as read"}

@router.get("/unread-count", response_model=GetUnreadCountResponse)
async def get_unread_count(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    未読通知数を取得
    """
    admin_count, users_count, payments_count = get_unread_count_crud(db, current_user)
    return GetUnreadCountResponse(
      admin=admin_count,
      users=users_count,
      payments=payments_count
    )