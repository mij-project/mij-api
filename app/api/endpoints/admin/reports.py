from fastapi import APIRouter, Depends, HTTPException

from app.crud.admin_reports_curd import (
    get_gmv_overalltime_report,
    get_gmv_period_report,
    get_payment_transactions_period_report,
    get_revenue_period_report,
    get_untransferred_withdraws_period_report,
)
from app.db.base import get_db
from app.deps.auth import get_current_admin_user
from app.models.admins import Admins
from sqlalchemy.orm import Session
from app.core.logger import Logger
from datetime import datetime, time, timedelta, timezone

logger = Logger.get_logger()
router = APIRouter()


@router.get("/gvm")
async def get_gvm_report(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting GVM reports for admin: {current_admin.id}")
    gmv_reports_overalltime = __get_gmv_overalltime_report(db)
    gmv_reports_period = __get_gmv_period_report(db, start_date, end_date)

    return {
        "gmv_overalltime": gmv_reports_overalltime["gmv_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "plan_gmv_overalltime": gmv_reports_overalltime["plan_gmv_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "single_gmv_overalltime": gmv_reports_overalltime["single_gmv_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "plan_count_overalltime": gmv_reports_overalltime["plan_count_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "single_count_overalltime": gmv_reports_overalltime["single_count_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "gmv_period": gmv_reports_period["gmv_period"] if gmv_reports_period else 0,
        "plan_gmv_period": gmv_reports_period["plan_gmv_period"]
        if gmv_reports_period
        else 0,
        "single_gmv_period": gmv_reports_period["single_gmv_period"]
        if gmv_reports_period
        else 0,
        "plan_count_period": gmv_reports_period["plan_count_period"]
        if gmv_reports_period
        else 0,
        "single_count_period": gmv_reports_period["single_count_period"]
        if gmv_reports_period
        else 0,
    }


def __get_gmv_overalltime_report(db: Session):
    return get_gmv_overalltime_report(db)


def __get_gmv_period_report(db: Session, start_date: str, end_date: str):
    start_date = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    end_date = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    return get_gmv_period_report(db, start_date, end_date)


@router.get("/revenue")
async def get_revenue_report(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting revenue reports for admin: {current_admin.id}")
    start_date = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    end_date = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    revenue_reports_period = get_revenue_period_report(db, start_date, end_date)
    if revenue_reports_period is None:
        raise HTTPException(status_code=500, detail="Error getting revenue reports")
    return revenue_reports_period


@router.get("/payment-transaction-fee")
async def get_payment_transactions_report(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting payment transactions reports for admin: {current_admin.id}")
    start_date = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    end_date = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    payment_transactions_reports_period = get_payment_transactions_period_report(
        db, start_date, end_date
    )
    if payment_transactions_reports_period is None:
        raise HTTPException(
            status_code=500, detail="Error getting payment transactions reports"
        )
    return payment_transactions_reports_period


@router.get("/untransferred-withdraws")
async def get_untransferred_withdraws_report(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(
        f"Getting untransferred withdraws reports for admin: {current_admin.id}"
    )
    start_date = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    end_date = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    untransferred_withdraws_reports_period = get_untransferred_withdraws_period_report(
        db, start_date, end_date
    )
    if untransferred_withdraws_reports_period is None:
        raise HTTPException(
            status_code=500, detail="Error getting untransferred withdraws reports"
        )
    return untransferred_withdraws_reports_period


@router.get("/credix-income")
async def get_credix_income_report(
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting credix income reports for admin: {current_admin.id}")
    now = datetime.now(timezone.utc)
    this_month = now.month
    previous_month = this_month - 1
    start_date_of_previous_month = datetime.combine(
        datetime.now(timezone.utc).replace(
            month=previous_month, day=1, hour=0, minute=0, second=0, microsecond=0
        ),
        time.min,
        tzinfo=timezone.utc,
    ) - timedelta(hours=9)
    end_date_of_previous_month = datetime.combine(
        datetime.now(timezone.utc).replace(
            month=previous_month, day=1, hour=0, minute=0, second=0, microsecond=0
        ),
        time.max,
        tzinfo=timezone.utc,
    ) - timedelta(hours=9)

    revenue_reports_period = get_revenue_period_report(
        db, start_date_of_previous_month, end_date_of_previous_month
    )
    payment_transactions_reports_period = get_payment_transactions_period_report(
        db, start_date_of_previous_month, end_date_of_previous_month
    )
    pevious_month_revenue = revenue_reports_period["total_platform_fee_gross"] or 0
    pevious_month_payment_transactions = (
        payment_transactions_reports_period["total_payment_transaction_fee"] or 0
    )
    total_income = max(pevious_month_revenue - pevious_month_payment_transactions, 0)

    return {
        "this_month": this_month,
        "previous_month": previous_month,
        "total_income": total_income,
    }
