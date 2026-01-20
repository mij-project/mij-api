from fastapi import APIRouter, Depends, HTTPException

from app.crud.admin_reports_curd import (
    get_credix_income_period_report,
    get_gmv_overalltime_report,
    get_gmv_period_report,
    get_credix_payment_transactions_period_report,
    get_revenue_period_report,
    get_untransferred_withdraws_period_report,
    get_payment_provider_revenue_period_report,
    get_payment_provider_revenue_last_month_report,
    get_albatal_income_period_report,
    get_albatal_payment_transactions_period_report,
    get_albatal_consolidated_monthly_income_report,
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
        "chip_gmv_overalltime": gmv_reports_overalltime["chip_gmv_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "plan_count_overalltime": gmv_reports_overalltime["plan_count_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "single_count_overalltime": gmv_reports_overalltime["single_count_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "chip_count_overalltime": gmv_reports_overalltime["chip_count_overalltime"]
        if gmv_reports_overalltime
        else 0,
        "plan_amount_gt0_count_overalltime": gmv_reports_overalltime[
            "plan_amount_gt0_count_overalltime"
        ]
        if gmv_reports_overalltime
        else 0,
        "single_amount_gt0_count_overalltime": gmv_reports_overalltime[
            "single_amount_gt0_count_overalltime"
        ]
        if gmv_reports_overalltime
        else 0,
        "plan_amount_zero_count_overalltime": gmv_reports_overalltime[
            "plan_amount_zero_count_overalltime"
        ]
        if gmv_reports_overalltime
        else 0,
        "single_amount_zero_count_overalltime": gmv_reports_overalltime[
            "single_amount_zero_count_overalltime"
        ]
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
        "plan_amount_gt0_count_period": gmv_reports_period[
            "plan_amount_gt0_count_period"
        ]
        if gmv_reports_period
        else 0,
        "single_amount_gt0_count_period": gmv_reports_period[
            "single_amount_gt0_count_period"
        ]
        if gmv_reports_period
        else 0,
        "plan_amount_zero_count_period": gmv_reports_period[
            "plan_amount_zero_count_period"
        ]
        if gmv_reports_period
        else 0,
        "single_amount_zero_count_period": gmv_reports_period[
            "single_amount_zero_count_period"
        ]
        if gmv_reports_period
        else 0,
        "chip_count_period": gmv_reports_period["chip_count_period"]
        if gmv_reports_period
        else 0,
        "chip_gmv_period": gmv_reports_period["chip_gmv_period"]
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


@router.get("/credix-payment-transaction-fee")
async def get_credix_payment_transactions_report(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(
        f"Getting credix payment transactions reports for admin: {current_admin.id}"
    )
    start_date = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    end_date = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    credix_payment_transactions_reports_period = (
        get_credix_payment_transactions_period_report(db, start_date, end_date)
    )
    if credix_payment_transactions_reports_period is None:
        raise HTTPException(
            status_code=500, detail="Error getting credix payment transactions reports"
        )
    return credix_payment_transactions_reports_period

@router.get("/albatal-payment-transaction-fee")
async def get_albatal_payment_transactions_report(
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(
        f"Getting albatal payment transactions reports for admin: {current_admin.id}"
    )
    start_date = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    end_date = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    albatal_payment_transactions_reports_period = get_albatal_payment_transactions_period_report(db, start_date, end_date)

    if albatal_payment_transactions_reports_period is None:
        raise HTTPException(
            status_code=500, detail="Error getting albatal payment transactions reports"
        )
    return albatal_payment_transactions_reports_period


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
    now_utc = datetime.now(timezone.utc)

    if now_utc.month == 1:
        prev_year = now_utc.year - 1
        prev_month = 12
    else:
        prev_year = now_utc.year
        prev_month = now_utc.month - 1

    # start of previous month (JST 00:00) expressed by your pattern
    start_date_of_previous_month = datetime(
        prev_year, prev_month, 1, 0, 0, 0, 0, tzinfo=timezone.utc
    ) - timedelta(hours=9)

    start_date_of_current_month = datetime(
        now_utc.year, now_utc.month, 1, 0, 0, 0, 0, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    end_date_of_previous_month = start_date_of_current_month - timedelta(microseconds=1)

    credix_income_report = get_credix_income_period_report(
        db, start_date_of_previous_month, end_date_of_previous_month
    )
    if credix_income_report is None:
        raise HTTPException(
            status_code=500, detail="Error getting credix income report"
        )
    total_income = credix_income_report["total_income"]
    return {
        "this_month": now_utc.month,
        "previous_month": prev_month,
        "total_income": total_income,
    }

@router.get("/albatal-income")
async def get_albatal_income_report(
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting albatal income reports for admin: {current_admin.id}")
    now_utc = datetime.now(timezone.utc)

    if now_utc.month == 1:
        prev_year = now_utc.year - 1
        prev_month = 12
    else:
        prev_year = now_utc.year
        prev_month = now_utc.month - 1

    albatal_income_report = get_albatal_income_period_report(db, now_utc)
    if albatal_income_report is None:
        raise HTTPException(
            status_code=500, detail="Error getting albatal income report"
        )

    # Get consolidated monthly income for the current month
    albatal_consolidated_report = get_albatal_consolidated_monthly_income_report(
        db, now_utc.year, now_utc.month
    )
    if albatal_consolidated_report is None:
        raise HTTPException(
            status_code=500, detail="Error getting albatal consolidated income report"
        )

    # Combine reports
    albatal_income_report["monthly_total_income"] = albatal_consolidated_report["monthly_total_income"]
    albatal_income_report["period1_total"] = albatal_consolidated_report["period2_total"]  
    albatal_income_report["period2_total"] = albatal_consolidated_report["period1_total"] 

    return albatal_income_report


@router.get("/provider-revenue")
async def get_provider_revenue_report(
    provider_code: str,
    start_date: str,
    end_date: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting provider revenue reports for admin: {current_admin.id}, provider: {provider_code}")
    start_date_dt = datetime.combine(
        datetime.strptime(start_date, "%Y-%m-%d"), time.min, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    end_date_dt = datetime.combine(
        datetime.strptime(end_date, "%Y-%m-%d"), time.max, tzinfo=timezone.utc
    ) - timedelta(hours=9)
    provider_revenue_report = get_payment_provider_revenue_period_report(
        db, provider_code, start_date_dt, end_date_dt
    )
    if provider_revenue_report is None:
        raise HTTPException(
            status_code=500, detail="Error getting provider revenue report"
        )
    return provider_revenue_report


@router.get("/provider-revenue-last-month")
async def get_provider_revenue_last_month_report(
    provider_code: str,
    db: Session = Depends(get_db),
    current_admin: Admins = Depends(get_current_admin_user),
):
    logger.info(f"Getting provider revenue last month report for admin: {current_admin.id}, provider: {provider_code}")
    provider_revenue_report = get_payment_provider_revenue_last_month_report(
        db, provider_code
    )
    if provider_revenue_report is None:
        raise HTTPException(
            status_code=500, detail="Error getting provider revenue last month report"
        )
    return provider_revenue_report
