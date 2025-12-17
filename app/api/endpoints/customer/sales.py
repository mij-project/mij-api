import calendar
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.constants.enums import WithdrawStatus
from app.core.logger import Logger
from app.crud.sales_crud import (
    create_withdrawal_application_by_user_id,
    get_latest_withdrawal_application_by_user_id,
    get_sales_history_by_creator,
    get_sales_period_by_creator,
    get_sales_summary_by_creator,
    get_withdrawal_application_histories_by_user_id,
)
from app.db.base import get_db
from app.models import Users
from app.deps.auth import get_current_user
from app.schemas.withdraw import (
    WithdrawalApplication,
    WithdrawalApplicationHistoryResponse,
    WithdrawalApplicationRequest,
)

from app.services.slack.slack import SlackService

slack_alert = SlackService.initialize()
logger = Logger.get_logger()
router = APIRouter()


@router.get("/sales-summary")
async def get_sales_summary(
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    summary = get_sales_summary_by_creator(db, current_user.id)
    if summary is None:
        raise HTTPException(status_code=500, detail="Sales summary not found")
    return summary


@router.get("/sales-period")
async def get_sales_period(
    period: str = Query("today"),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    logger.info(f"Sales period: {period}")
    if period in ["today", "yesterday", "day_before_yesterday"]:
        return _get_sales_period_date_range(db, period, current_user)
    return _get_sales_period_month_range(db, period, current_user)


def _get_sales_period_date_range(db: Session, period: str, current_user: Users):
    now = datetime.now(timezone.utc)
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(hours=9)
        previous_start_date = start_date - timedelta(days=1)
        previous_end_date = end_date - timedelta(days=1)
    elif period == "yesterday":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=1, hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(days=1, hours=9)
        previous_start_date = start_date - timedelta(days=1)
        previous_end_date = end_date - timedelta(days=1)
    elif period == "day_before_yesterday":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=2, hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(days=2, hours=9)
        previous_start_date = start_date - timedelta(days=3)
        previous_end_date = end_date - timedelta(days=3)
    else:
        raise HTTPException(status_code=400, detail="Invalid period")
    period_sales = get_sales_period_by_creator(
        db,
        current_user.id,
        start_date,
        end_date,
        previous_start_date,
        previous_end_date,
    )
    if period_sales is None:
        raise HTTPException(status_code=500, detail="Sales period not found")
    return period_sales


def _get_sales_period_month_range(db: Session, period: str, current_user: Users):
    start_date, end_date, previous_start_date, previous_end_date = __get_month_ranges(
        period
    )
    period_sales = get_sales_period_by_creator(
        db,
        current_user.id,
        start_date,
        end_date,
        previous_start_date,
        previous_end_date,
    )
    if period_sales is None:
        raise HTTPException(status_code=500, detail="Sales period not found")
    return period_sales


def __get_month_ranges(ym: str):
    year, month = map(int, ym.split("-"))

    start_date = datetime(year, month, 1, 0, 0, 0) - timedelta(hours=9)

    last_day = calendar.monthrange(year, month)[1]
    end_date = datetime(year, month, last_day, 23, 59, 59, 999_999) - timedelta(hours=9)

    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1

    prev_start_date = datetime(prev_year, prev_month, 1, 0, 0, 0) - timedelta(hours=9)
    prev_last_day = calendar.monthrange(prev_year, prev_month)[1]
    prev_end_date = datetime(
        prev_year, prev_month, prev_last_day, 23, 59, 59, 999_999
    ) - timedelta(hours=9)

    return (start_date, end_date, prev_start_date, prev_end_date)


@router.get("/sales-history")
async def get_sales_history(
    period: str = Query("today"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    logger.info(f"Sales history period: {period}")
    if period in ["today", "yesterday", "day_before_yesterday"]:
        return _get_sales_history_period_date_range(
            db, period, current_user, page, limit
        )
    return _get_sales_history_period_month_range(db, period, current_user, page, limit)


def _get_sales_history_period_date_range(
    db: Session, period: str, current_user: Users, page: int, limit: int
):
    now = datetime.now(timezone.utc)
    if period == "today":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(hours=9)
    elif period == "yesterday":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=1, hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(days=1, hours=9)
    elif period == "day_before_yesterday":
        start_date = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=2, hours=9
        )
        end_date = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(days=2, hours=9)
    else:
        raise HTTPException(status_code=400, detail="Invalid period")
    sales_history = get_sales_history_by_creator(
        db, current_user.id, start_date, end_date, page, limit
    )
    if sales_history is None:
        raise HTTPException(status_code=500, detail="Sales history not found")
    total_pages, has_next, has_previous = __process_pagination(
        sales_history["payments"], page, limit, sales_history["total"]
    )
    return {
        "payments": sales_history["payments"],
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_previous": has_previous,
    }


def _get_sales_history_period_month_range(
    db: Session, period: str, current_user: Users, page: int, limit: int
):
    start_date, end_date, previous_start_date, previous_end_date = __get_month_ranges(
        period
    )
    sales_history = get_sales_history_by_creator(
        db, current_user.id, start_date, end_date, page, limit
    )
    if sales_history is None:
        raise HTTPException(status_code=500, detail="Sales history not found")
    total_pages, has_next, has_previous = __process_pagination(
        sales_history["payments"], page, limit, sales_history["total"]
    )
    return {
        "payments": sales_history["payments"],
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_next": has_next,
        "has_previous": has_previous,
    }


def __process_pagination(result: list, page: int, limit: int, total: int):
    total_pages = (total + limit - 1) // limit
    has_next = page < total_pages
    has_previous = page > 1
    return total_pages, has_next, has_previous


@router.post("/withdrawal-application")
async def create_withdrawal_application(
    withdrawal_application_request: WithdrawalApplicationRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    logger.info(
        f"Withdrawal application request: {withdrawal_application_request} for user: {current_user.id}"
    )
    if not __validate_withdrawal_application_request(db, current_user):
        raise HTTPException(
            status_code=400, detail="Latest withdrawal application is not allowed"
        )
    success = create_withdrawal_application_by_user_id(
        db, current_user.id, withdrawal_application_request
    )
    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to create withdrawal application"
        )
    slack_alert._alert_withdrawal_request(current_user.profile_name)

    return {"message": "Ok"}


def __validate_withdrawal_application_request(
    db: Session,
    current_user: Users,
):
    latest_withdrawal_application = get_latest_withdrawal_application_by_user_id(
        db, current_user.id
    )
    if latest_withdrawal_application is None:
        return True
    if latest_withdrawal_application.status in [
        WithdrawStatus.PENDING,
        WithdrawStatus.PROCESSING,
    ]:
        return False
    if latest_withdrawal_application.created_at.replace(
        tzinfo=timezone.utc
    ) + timedelta(days=1) < datetime.now(timezone.utc):
        return False
    return True


@router.get("/withdrawal-histories")
async def get_withdrawal_application_histories(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    withdrawal_applications = get_withdrawal_application_histories_by_user_id(
        db, current_user.id, page, limit
    )
    if withdrawal_applications is None:
        raise HTTPException(status_code=500, detail="Withdrawal applications not found")
    total_pages, has_next, has_previous = __process_pagination(
        withdrawal_applications["withdrawal_applications"],
        page,
        limit,
        withdrawal_applications["total_count"],
    )
    withdrawal_applications_items = [
        WithdrawalApplication(
            id=str(withdrawal_application.id),
            withdraw_amount=withdrawal_application.withdraw_amount,
            transfer_amount=withdrawal_application.transfer_amount,
            status=withdrawal_application.status,
            requested_at=withdrawal_application.requested_at,
            failure_code=withdrawal_application.failure_code,
            failure_message=withdrawal_application.failure_message,
        )
        for withdrawal_application in withdrawal_applications["withdrawal_applications"]
    ]
    return WithdrawalApplicationHistoryResponse(
        withdrawal_applications=withdrawal_applications_items,
        page=page,
        limit=limit,
        total_pages=total_pages,
        has_next=has_next,
        has_previous=has_previous,
    )
