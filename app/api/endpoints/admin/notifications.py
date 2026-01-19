from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.crud.notifications_curd import create_notification_admin, get_notifications_admin_paginated, update_notification_admin
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.models.admins import Admins
from app.schemas.notification import NotificationCreateRequest, NotificationCreateResponse, PaginatedNotificationAdminResponse

router = APIRouter()

@router.get("", response_model=PaginatedNotificationAdminResponse)
async def get_notifications(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    sort: Optional[str] = "created_at_desc",
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
) -> PaginatedNotificationAdminResponse:
    """
    管理者用の通知一覧を取得

    Args:
        page: ページ番号（1から開始）
        limit: 1ページあたりの件数（1-100）
        search: 検索クエリ（通知タイトル、通知内容）
        sort: ソート順（created_at_desc/created_at_asc）

    Returns:
        PaginatedNotificationAdminResponse
    """
    if not current_admin: 
      raise HTTPException(status_code=401, detail="Unauthorized")

    notifications, total = get_notifications_admin_paginated(
        db=db,
        page=page,
        limit=limit,
        search=search,
        sort=sort
    )

    return PaginatedNotificationAdminResponse(
        notifications=[NotificationCreateResponse(
          id=n.id,
          type=n.type,
          payload=n.payload,
          is_read=n.is_read,
          read_at=n.read_at,
          target_role=n.target_role,
          created_at=n.created_at,
          updated_at=n.updated_at
        ) for n in notifications],
        total=total,
        page=page,
        limit=limit,
        total_pages=(total + limit - 1) // limit if total > 0 else 1
    )

@router.post("", response_model=NotificationCreateResponse)
async def create_notification(
    notification: NotificationCreateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
) -> NotificationCreateResponse:
    """
    通知を作成
    """
    if not current_admin:
      raise HTTPException(status_code=401, detail="Unauthorized")
    done = create_notification_admin(db=db, notification=notification)
    if not done:
      raise HTTPException(status_code=500, detail="Failed to create notification")
    return NotificationCreateResponse(
      id=done.id,
      type=done.type,
      target_role=done.target_role,
      payload=done.payload,
      is_read=done.is_read,
      read_at=done.read_at,
      created_at=done.created_at,
      updated_at=done.updated_at
    )

@router.put("/{notification_id}", response_model=NotificationCreateResponse)
async def update_notification(
    notification_id: UUID,
    notification_update: NotificationCreateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user)
) -> NotificationCreateResponse:
    """
    通知を更新
    """
    if not current_admin:
      raise HTTPException(status_code=401, detail="Unauthorized")
    done = update_notification_admin(db=db, notification_id=notification_id, notification_update=notification_update)
    if not done:
      raise HTTPException(status_code=500, detail="Failed to update notification")
    return NotificationCreateResponse(
      id=done.id,
      type=done.type,
      target_role=done.target_role,
      payload=done.payload,
      is_read=done.is_read,
      read_at=done.read_at,
      created_at=done.created_at,
      updated_at=done.updated_at
    )