from datetime import datetime, time, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.models.admins import Admins
from app.core.logger import Logger
from app.crud.admin_subscriptions_curd import (
    get_subscriptions_info,
    get_subscriptions_summary,
)
from app.schemas.subscriptions import (
    SubscriptionAdminInfo,
    SubscriptionAdminInfoResponse,
)

logger = Logger.get_logger()
router = APIRouter()


@router.get("/subscriptions-summary")
async def get_subscriptions_summary_for_admin(
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting subscriptions summary for admin: {current_admin.id}")
    subscriptions_summary = get_subscriptions_summary(db)
    if subscriptions_summary is None:
        raise HTTPException(
            status_code=500, detail="Failed to get subscriptions summary"
        )
    return subscriptions_summary


@router.get("/subscriptions")
async def get_subscriptions_for_admin(
    start_date: str,
    end_date: str,
    filter: int = Query(0, description="0=all, 1=active, 2=failed"),
    page: int = Query(1, description="Page number"),
    limit: int = Query(20, description="Items per page"),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(
        f"Getting subscriptions info for admin: {current_admin.id}, start_date: {start_date}, end_date: {end_date}, filter: {filter}"
    )
    start_date = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min
    ) - timedelta(hours=9)
    end_date = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max
    ) - timedelta(hours=9)
    subscriptions_info = get_subscriptions_info(
        db, start_date, end_date, filter, page, limit
    )
    if subscriptions_info is None:
        raise HTTPException(status_code=500, detail="Failed to get subscriptions info")
    subscriptions_admin_info = []
    for subscription in subscriptions_info["subscriptions"]:
        if subscription.Subscriptions.status == 1:
            status = 1
        elif subscription.Subscriptions.status == 2:
            status = 1
        elif (
            subscription.Subscriptions.status == 3
            and subscription.Subscriptions.last_payment_failed_at is None
        ):
            status = 3
        elif (
            subscription.Subscriptions.status == 3
            and subscription.Subscriptions.last_payment_failed_at is not None
        ):
            status = 2

        subscriptions_admin_info.append(
            SubscriptionAdminInfo(
                id=str(subscription.Subscriptions.id),
                subscriber_username=subscription.subscriber_username,
                creator_username=subscription.creator_username,
                status=status,
                money=subscription.money,
                payment_amount=subscription.payment_amount,
                access_start=subscription.Subscriptions.access_start,
                access_end=subscription.Subscriptions.access_end,
                canceled_at=subscription.Subscriptions.canceled_at,
                next_billing_date=subscription.Subscriptions.next_billing_date,
                last_payment_failed_at=subscription.Subscriptions.last_payment_failed_at,
            )
        )
    total_items = subscriptions_info["total_items"]
    total_pages = (total_items + limit - 1) // limit if total_items > 0 else 1

    return SubscriptionAdminInfoResponse(
        subscriptions=subscriptions_admin_info,
        total_items=total_items,
        page=page,
        limit=limit,
        total_pages=total_pages,
    )
