from datetime import datetime, time, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.commons.base64helper import decode_b64
from app.crud.creator_crud import update_creator_platform_fee_by_admin
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.models.admins import Admins
from app.core.logger import Logger
from app.crud.sales_crud import (
    get_creators_sales_by_period,
    get_creators_withdraw_summary_by_period_for_admin,
    get_creators_withdrawals_by_period_for_admin,
    update_withdrawal_application_status_by_admin,
)
from app.schemas.creator import CreatorPlatformFeeUpdateRequest
from app.schemas.withdraw import (
    WithdrawalApplicationHistoryForAdmin,
    WithdrawalApplicationHistoryResponseForAdmin,
    WithdrawalApplicationUpdateRequest,
)

logger = Logger.get_logger()
router = APIRouter()


@router.get("/creators-sales")
def get_creators_sales(
    start_date: str,
    end_date: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None, description="検索クエリ（名前・コード）"),
    sort: str = Query(
        "newest",
        description="newest/sales_desc/sales_asc/name_asc",
    ),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting creators sales from {start_date} to {end_date} ")
    start_date = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
    )
    end_date = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
    )
    rs = get_creators_sales_by_period(
        db, start_date, end_date, page, limit, search, sort
    )
    if rs is None:
        raise HTTPException(status_code=500, detail="Failed to get creators sales")
    return rs


@router.get("/creators-withdrawals-summary")
def get_creators_withdrawals_summary(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(
        f"Getting creators sales summary from {start_date} to {end_date} admin: {current_admin.id}"
    )
    if start_date and end_date:
        start_date = datetime.combine(
            datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
        ) - timedelta(hours=9)
        end_date = datetime.combine(
            datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
        ) - timedelta(hours=9)
        rs = get_creators_withdraw_summary_by_period_for_admin(db, start_date, end_date)
    else:
        rs = get_creators_withdraw_summary_by_period_for_admin(db)

    if rs is None:
        raise HTTPException(
            status_code=500, detail="Failed to get creators withdraw summary"
        )
    return rs


@router.get("/creators-withdrawals-by-period")
def get_creators_withdrawals_by_period(
    start_date: str,
    end_date: str,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    filter: int = Query(
        0,
        description="0=all, 1=pending, 2=processing, 3=completed, 4=failed, 5=cancelled",
    ),
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(
        f"Getting creators withdrawals by period from {start_date} to {end_date} admin: {current_admin.id}"
    )
    if start_date and end_date:
        start_date = datetime.combine(
            datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
        ) - timedelta(hours=9)
        end_date = datetime.combine(
            datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
        ) - timedelta(hours=9)
    results = get_creators_withdrawals_by_period_for_admin(
        db, start_date, end_date, page, limit, filter
    )
    if results is None:
        raise HTTPException(
            status_code=500, detail="Failed to get creators withdrawals by period"
        )
    withdrawals = [
        WithdrawalApplicationHistoryForAdmin(
            id=str(withdrawal.Withdraws.id),
            withdraw_amount=withdrawal.Withdraws.withdraw_amount,
            transfer_amount=withdrawal.Withdraws.transfer_amount,
            status=withdrawal.Withdraws.status,
            requested_at=withdrawal.Withdraws.requested_at,
            account_holder_name=decode_b64(withdrawal.account_holder_name),
            account_number=decode_b64(withdrawal.account_number),
            account_type=withdrawal.account_type,
            bank_name=withdrawal.bank_name,
            bank_code=withdrawal.bank_code,
            branch_name=withdrawal.branch_name,
            branch_code=withdrawal.branch_code,
            creator_username=withdrawal.creator_username,
            failure_code=withdrawal.Withdraws.failure_code,
            failure_message=withdrawal.Withdraws.failure_message,
            completed_at=withdrawal.Withdraws.completed_at,
        )
        for withdrawal in results["withdrawals"]
    ]
    response = WithdrawalApplicationHistoryResponseForAdmin(
        withdrawal_applications=withdrawals,
        total_count=results["total_count"],
        total_pages=results["total_pages"],
        page=page,
        limit=limit,
    )
    return response


@router.post("/withdrawal-application-update")
async def update_withdrawal_application(
    payload: WithdrawalApplicationUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(
        f"Updating withdrawal application {payload.application_id} with status {payload.status}"
    )
    success = update_withdrawal_application_status_by_admin(
        db, payload.application_id, payload.status, admin_id=current_admin.id
    )
    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to update withdrawal application"
        )
    return {"message": "Ok"}


@router.post("/creator-platform-fee-update")
async def update_creator_platform_fee(
    payload: CreatorPlatformFeeUpdateRequest,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(
        f"Updating creator platform fee {payload.creator_id} with platform fee {payload.platform_fee}"
    )
    success = update_creator_platform_fee_by_admin(
        db, payload.creator_id, payload.platform_fee
    )
    if not success:
        raise HTTPException(
            status_code=500, detail="Failed to update creator platform fee"
        )
    return {"message": "Ok"}
