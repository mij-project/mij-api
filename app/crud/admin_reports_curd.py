from datetime import datetime, timezone, timedelta
import math
from typing import Optional

from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from app.constants.enums import PaymentStatus, PaymentType, WithdrawStatus, PaymentTransactionStatus
from app.core.logger import Logger
from app.models import CompanyUsers, Payments, Withdraws
from app.models.payment_transactions import PaymentTransactions
from app.models.providers import Providers

logger = Logger.get_logger()


def get_gmv_overalltime_report(db: Session) -> Optional[dict]:
    try:
        amt = func.coalesce(Payments.payment_amount, 0)

        stmt = select(
            # GMV all-time (SUCCEEDED)
            func.coalesce(
                func.sum(
                    case(
                        (
                            Payments.status == PaymentStatus.SUCCEEDED,
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("gmv_overalltime"),
            # Plan GMV all-time (SUCCEEDED & PLAN)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.PLAN),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_gmv_overalltime"),
            # Single GMV all-time (SUCCEEDED & SINGLE)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.SINGLE),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_gmv_overalltime"),
            # Chip GMV all-time (SUCCEEDED & CHIP)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.CHIP),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("chip_gmv_overalltime"),
            # Plan COUNT all-time (SUCCEEDED & PLAN)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.PLAN),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_count_overalltime"),
            # Single COUNT all-time (SUCCEEDED & SINGLE)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.SINGLE),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_count_overalltime"),
            # Chip COUNT all-time (SUCCEEDED & CHIP)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.CHIP),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("chip_count_overalltime"),
            # --- NEW: Single amount breakdown (SUCCEEDED & SINGLE) ---
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.SINGLE)
                            & (amt == 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_amount_zero_count_overalltime"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.SINGLE)
                            & (amt > 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_amount_gt0_count_overalltime"),
            # --- NEW: Plan amount breakdown (SUCCEEDED & PLAN) ---
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.PLAN)
                            & (amt == 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_amount_zero_count_overalltime"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.PLAN)
                            & (amt > 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_amount_gt0_count_overalltime"),
        )

        row = db.execute(stmt).one()

        return {
            "gmv_overalltime": row.gmv_overalltime,
            "plan_gmv_overalltime": row.plan_gmv_overalltime,
            "single_gmv_overalltime": row.single_gmv_overalltime,
            "chip_gmv_overalltime": row.chip_gmv_overalltime,
            "plan_count_overalltime": row.plan_count_overalltime,
            "single_count_overalltime": row.single_count_overalltime,
            "chip_count_overalltime": row.chip_count_overalltime,
            # NEW
            "single_amount_zero_count_overalltime": row.single_amount_zero_count_overalltime,
            "single_amount_gt0_count_overalltime": row.single_amount_gt0_count_overalltime,
            "plan_amount_zero_count_overalltime": row.plan_amount_zero_count_overalltime,
            "plan_amount_gt0_count_overalltime": row.plan_amount_gt0_count_overalltime,
        }
    except Exception as e:
        logger.error(f"Error getting revenue reports: {e}")
        return None


def get_gmv_period_report(
    db: Session, start_date: datetime, end_date: datetime
) -> Optional[dict]:
    try:
        # convert to naive datetime
        start_date = start_date.replace(tzinfo=None)
        end_date = end_date.replace(tzinfo=None)

        conditions = [
            Payments.created_at >= start_date,
            Payments.created_at <= end_date,
        ]

        amt = func.coalesce(Payments.payment_amount, 0)

        stmt = select(
            # GMV in period
            func.coalesce(
                func.sum(
                    case(
                        (
                            Payments.status == PaymentStatus.SUCCEEDED,
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("gmv_period"),
            # Plan GMV in period (SUCCEEDED & PLAN)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.PLAN),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_gmv_period"),
            # Single GMV in period (SUCCEEDED & SINGLE)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.SINGLE),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_gmv_period"),
            # Chip GMV in period (SUCCEEDED & CHIP)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.CHIP),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("chip_gmv_period"),
            # Plan COUNT in period (SUCCEEDED & PLAN)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.PLAN),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_count_period"),
            # Single COUNT in period (SUCCEEDED & SINGLE)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.SINGLE),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_count_period"),
            # Chip COUNT in period (SUCCEEDED & CHIP)
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.CHIP),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("chip_count_period"),
            # --- amount breakdown: SINGLE ---
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.SINGLE)
                            & (amt == 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_amount_zero_count_period"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.SINGLE)
                            & (amt > 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_amount_gt0_count_period"),
            # --- amount breakdown: PLAN ---
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.PLAN)
                            & (amt == 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_amount_zero_count_period"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.PLAN)
                            & (amt > 0),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_amount_gt0_count_period"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            & (Payments.payment_type == PaymentType.CHIP),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("chip_gmv_period")
        ).where(*conditions)

        row = db.execute(stmt).one()

        return {
            "gmv_period": row.gmv_period,
            "plan_gmv_period": row.plan_gmv_period,
            "single_gmv_period": row.single_gmv_period,
            "chip_gmv_period": row.chip_gmv_period,
            "plan_count_period": row.plan_count_period,
            "single_count_period": row.single_count_period,
            "chip_count_period": row.chip_count_period,
            "single_amount_zero_count_period": row.single_amount_zero_count_period,
            "single_amount_gt0_count_period": row.single_amount_gt0_count_period,
            "plan_amount_zero_count_period": row.plan_amount_zero_count_period,
            "plan_amount_gt0_count_period": row.plan_amount_gt0_count_period,
        }
    except Exception as e:
        logger.error(f"Error getting revenue period reports: {e}")
        return None


def get_revenue_period_report(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Optional[dict]:
    try:
        conditions_payments = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
            Payments.payment_amount > 0,
        ]
        if start_date is not None:
            conditions_payments.append(
                Payments.paid_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            conditions_payments.append(
                Payments.paid_at <= end_date.replace(tzinfo=None)
            )

        stmt = (
            select(
                Payments,
                func.coalesce(CompanyUsers.company_fee_percent, 0).label(
                    "company_fee_percent"
                ),
                Providers.settings.label("provider_settings"),
                Providers.code.label("provider_code"),
            )
            .join(Providers, Providers.id == Payments.provider_id)
            .outerjoin(
                CompanyUsers,
                CompanyUsers.user_id == Payments.seller_user_id,
            )
            .where(*conditions_payments)
        )
        payments_row = db.execute(stmt).all()
        total_platform_fee_from_payments = 0
        total_revenue = 0
        revenue_from_payments = []

        for row in payments_row:
            payment_price = row.Payments.payment_price
            payment_amount = row.Payments.payment_amount
            platform_fee = row.Payments.platform_fee
            provider_code = row.provider_code
            company_fee_percent = row.company_fee_percent
            provider_settings = row.provider_settings

            platform_fee_per_payment = math.ceil(payment_price * platform_fee / 100)
            company_fee_per_payment = round(
                platform_fee_per_payment * company_fee_percent / 100
            )
            platform_fee_per_payment_after_company = (
                platform_fee_per_payment - company_fee_per_payment
            )
            total_platform_fee_from_payments += platform_fee_per_payment_after_company

            margin_per_payment = payment_amount - payment_price
            provider_fee_per_payment = round(
                payment_amount * provider_settings.get("fee", 0) / 100, 3
            ) + provider_settings.get("tx_successs_fee", 0)
            revenue_per_payment = round(
                margin_per_payment - provider_fee_per_payment, 3
            )

            provider_exists = [
                x for x in revenue_from_payments if x["provider_code"] == provider_code
            ]
            if provider_exists:
                provider_exists[0]["revenue_from_payments"] += revenue_per_payment
            else:
                revenue_from_payments.append(
                    {
                        "provider_code": provider_code,
                        "revenue_from_payments": revenue_per_payment,
                    }
                )

        # ---- approved withdraws ----
        withdraws_approved_conditions = [
            Withdraws.status == WithdrawStatus.COMPLETED,
        ]

        if start_date is not None:
            withdraws_approved_conditions.append(
                Withdraws.approved_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            withdraws_approved_conditions.append(
                Withdraws.approved_at <= end_date.replace(tzinfo=None)
            )

        approved_stmt = select(func.coalesce(func.count(Withdraws.id), 0)).where(
            *withdraws_approved_conditions
        )

        approved_withdraw_count = db.execute(approved_stmt).scalar() or 0
        withdraws_approved_profit = approved_withdraw_count * 187

        total_revenue = round(
            total_platform_fee_from_payments + withdraws_approved_profit, 3
        )

        for x in revenue_from_payments:
            total_revenue = round(total_revenue + x["revenue_from_payments"], 3)

        return {
            "approved_withdraw_count": approved_withdraw_count,
            "withdraws_approved_profit": withdraws_approved_profit,
            "total_revenue": total_revenue,
            "total_platform_revenue_from_payments": total_platform_fee_from_payments,
            "revenue_from_payments": revenue_from_payments,
        }

    except Exception as e:
        logger.error(f"Error getting revenue overalltime reports: {e}")
        return None


def get_credix_payment_transactions_period_report(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Optional[dict]:
    try:
        # Fail payment count
        fail_paymenttransaction_conditions = [PaymentTransactions.status == 3]
        if start_date is not None:
            fail_paymenttransaction_conditions.append(
                PaymentTransactions.created_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            fail_paymenttransaction_conditions.append(
                PaymentTransactions.created_at <= end_date.replace(tzinfo=None)
            )

        failed_stmt = (
            select(func.coalesce(func.count(PaymentTransactions.id), 0))
            .select_from(PaymentTransactions)
            .join(Providers, PaymentTransactions.provider_id == Providers.id)
            .where(
                Providers.code == "credix",
                *fail_paymenttransaction_conditions,
            )
        )
        failed_row = db.execute(failed_stmt).scalar() or 0
        # Success payment count
        success_paymenttransaction_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
        ]
        if start_date is not None:
            success_paymenttransaction_conditions.append(
                Payments.paid_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            success_paymenttransaction_conditions.append(
                Payments.paid_at <= end_date.replace(tzinfo=None)
            )

        fee_per_payment = func.round(
            func.round(Payments.payment_amount * 0.077, 3) + 55, 3
        )
        fee_per_payment_transaction_fee_excluding = func.round(
            Payments.payment_amount * 0.077, 3
        )

        success_stmt = (
            select(
                func.coalesce(
                    func.sum(fee_per_payment),
                    0,
                ).label("total_transaction_fee"),
                func.coalesce(
                    func.sum(fee_per_payment_transaction_fee_excluding),
                    0,
                ).label("total_payment_transaction_fee_excluding"),
                func.coalesce(
                    func.count(Payments.id),
                    0,
                ).label("successful_payment_transaction_count"),
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == "credix",
                *success_paymenttransaction_conditions,
            )
        )
        success_row = db.execute(success_stmt).one()
        total_payment_transaction_fee = float(
            success_row.total_transaction_fee + (failed_row * 44) + 33000
        )
        return {
            "failed_payment_transaction_fee": failed_row * 44,
            "failed_payment_transaction_count": failed_row,
            "success_payment_transaction_fee": success_row.total_transaction_fee,
            "success_payment_transaction_count": success_row.successful_payment_transaction_count,
            "total_payment_transaction_fee": total_payment_transaction_fee,
            "total_payment_transaction_fee_excluding": success_row.total_payment_transaction_fee_excluding,
        }
    except Exception as e:
        logger.error(f"Error getting payment transactions period reports: {e}")
        return None


def get_untransferred_withdraws_period_report(
    db: Session,
    start_date: datetime,
    end_date: datetime,
) -> Optional[dict]:
    try:
        # In period
        start_date = start_date.replace(tzinfo=None)
        end_date = end_date.replace(tzinfo=None)

        conditions_withdraws_in_period = [
            Withdraws.status == WithdrawStatus.COMPLETED,
            Withdraws.approved_at >= start_date,
            Withdraws.approved_at <= end_date,
        ]

        withdraws_stmt_in_period = select(
            func.coalesce(func.sum(Withdraws.withdraw_amount), 0).label(
                "total_withdraws"
            ),
        ).where(*conditions_withdraws_in_period)
        withdraws_in_period_row = db.execute(withdraws_stmt_in_period).one()

        conditions_payment_in_period = [
            Payments.created_at >= start_date,
            Payments.created_at <= end_date,
            Payments.payment_price > 0,
        ]
        stmt_payment_in_period = select(
            func.coalesce(
                func.sum(Payments.payment_price),
                0,
            ).label("total_payment_price"),
        ).where(*conditions_payment_in_period)

        row_payment_in_period = db.execute(stmt_payment_in_period).one()
        total_payment_price_in_period = row_payment_in_period.total_payment_price
        total_withdraws_in_period = withdraws_in_period_row.total_withdraws or 0
        untransferred_amount_in_period = (
            total_payment_price_in_period - total_withdraws_in_period
        )

        # Overalltime
        conditions_withdraws_overtime = [
            Withdraws.status == WithdrawStatus.COMPLETED,
        ]
        withdraws_stmt_overalltime = select(
            func.coalesce(func.sum(Withdraws.withdraw_amount), 0).label(
                "total_withdraws"
            ),
        ).where(*conditions_withdraws_overtime)
        withdraws_overalltime_row = db.execute(withdraws_stmt_overalltime).one()

        conditions_payment_overtime = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
        ]
        stmt_payment_overtime = select(
            func.coalesce(
                func.sum(Payments.payment_price),
                0,
            ).label("total_payment_price"),
        ).where(*conditions_payment_overtime)
        row_payment_overtime = db.execute(stmt_payment_overtime).one()
        total_payment_price_overtime = row_payment_overtime.total_payment_price
        total_withdraws_overtime = withdraws_overalltime_row.total_withdraws or 0
        untransferred_amount_overalltime = (
            total_payment_price_overtime - total_withdraws_overtime
        )

        return {
            "untransferred_amount_in_period": untransferred_amount_in_period,
            "untransferred_amount_overalltime": untransferred_amount_overalltime,
        }
    except Exception as e:
        logger.error(f"Error getting untransferred amount period reports: {e}")
        return None


def get_credix_income_period_report(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Optional[dict]:
    try:
        credix_payment_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
        ]

        if start_date is not None:
            credix_payment_conditions.append(
                Payments.paid_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            credix_payment_conditions.append(
                Payments.paid_at <= end_date.replace(tzinfo=None)
            )

        credix_payments_stmt = (
            select(
                Payments,
                func.coalesce(CompanyUsers.company_fee_percent, 0).label(
                    "company_fee_percent"
                ),
                Providers.settings.label("provider_settings"),
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .outerjoin(
                CompanyUsers,
                CompanyUsers.user_id == Payments.seller_user_id,
            )
            .where(
                Providers.code == "credix",
                *credix_payment_conditions,
            )
        )

        credix_rows = db.execute(credix_payments_stmt).all()

        total_payment_amount = 0

        for row in credix_rows:
            payment_amount = row.Payments.payment_amount
            total_payment_amount += payment_amount

        credix_fee = get_credix_payment_transactions_period_report(
            db, start_date, end_date
        )
        if credix_fee is None:
            return None
        total_payment_transaction_fee = credix_fee["total_payment_transaction_fee"]

        total_income = max(
            round(total_payment_amount - total_payment_transaction_fee, 3), 0
        )

        return {
            "total_income": total_income,
        }
    except Exception as e:
        logger.error(f"Error getting credix income report: {e}")
        return None


def get_payment_provider_revenue_period_report(
    db: Session,
    provider_code: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Optional[dict]:
    """Get payment revenue for a specific provider in a period"""
    try:
        payment_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
        ]

        if start_date is not None:
            payment_conditions.append(
                Payments.paid_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            payment_conditions.append(
                Payments.paid_at <= end_date.replace(tzinfo=None)
            )

        stmt = (
            select(
                func.coalesce(
                    func.sum(Payments.payment_amount),
                    0,
                ).label("total_amount"),
                func.coalesce(
                    func.count(Payments.id),
                    0,
                ).label("transaction_count"),
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == provider_code,
                *payment_conditions,
            )
        )

        row = db.execute(stmt).one()

        return {
            "total_amount": row.total_amount or 0,
            "transaction_count": row.transaction_count or 0,
        }
    except Exception as e:
        logger.error(f"Error getting payment provider revenue report: {e}")
        return None


def get_payment_provider_revenue_last_month_report(
    db: Session,
    provider_code: str,
) -> Optional[dict]:
    """Get payment revenue for a specific provider for previous month with fee deduction"""
    try:
        now_utc = datetime.now(timezone.utc)

        # Calculate previous month
        if now_utc.month == 1:
            prev_year = now_utc.year - 1
            prev_month = 12
        else:
            prev_year = now_utc.year
            prev_month = now_utc.month - 1

        # Start of previous month (JST 00:00)
        start_date = datetime(
            prev_year, prev_month, 1, 0, 0, 0, 0, tzinfo=timezone.utc
        ) - timedelta(hours=9)

        # Start of current month (JST 00:00)
        start_date_of_current_month = datetime(
            now_utc.year, now_utc.month, 1, 0, 0, 0, 0, tzinfo=timezone.utc
        ) - timedelta(hours=9)
        end_date = start_date_of_current_month - timedelta(microseconds=1)

        # Get provider with settings using LEFT JOIN to handle no data case
        stmt = (
            select(
                func.coalesce(
                    func.sum(Payments.payment_amount),
                    0,
                ).label("total_amount"),
                func.coalesce(
                    func.count(Payments.id),
                    0,
                ).label("transaction_count"),
                Providers.settings.label("provider_settings"),
            )
            .select_from(Providers)
            .outerjoin(
                Payments,
                (Payments.provider_id == Providers.id)
                & (Payments.status == PaymentStatus.SUCCEEDED)
                & (Payments.payment_price > 0)
                & (Payments.paid_at >= start_date.replace(tzinfo=None))
                & (Payments.paid_at <= end_date.replace(tzinfo=None)),
            )
            .where(Providers.code == provider_code)
            .group_by(Providers.id, Providers.settings)
        )

        row = db.execute(stmt).one_or_none()

        if row is None:
            # No provider found
            return {
                "total_amount": 0,
                "net_amount": 0,
                "total_fee": 0,
                "transaction_count": 0,
                "previous_month": prev_month,
                "fee_percent": 0,
            }

        total_amount = int(row.total_amount or 0)
        transaction_count = int(row.transaction_count or 0)
        provider_settings = row.provider_settings or {}

        # Calculate fee and net amount
        fee_percent = float(provider_settings.get("fee", 0))
        tx_success_fee = float(provider_settings.get("tx_successs_fee", 0))

        total_fee = math.ceil(total_amount * fee_percent / 100) + int(transaction_count * tx_success_fee)
        net_amount = max(total_amount - total_fee, 0)

        return {
            "total_amount": total_amount,
            "net_amount": net_amount,
            "total_fee": total_fee,
            "transaction_count": transaction_count,
            "previous_month": prev_month,
            "fee_percent": fee_percent,
        }
    except Exception as e:
        logger.error(f"Error getting payment provider revenue last month report: {e}")
        return None


def get_albatal_payment_transactions_period_report(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Optional[dict]:
    try:
        # Failed payment transaction count
        fail_paymenttransaction_conditions = [PaymentTransactions.status == PaymentTransactionStatus.FAILED]
        if start_date is not None:
            fail_paymenttransaction_conditions.append(
                PaymentTransactions.created_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            fail_paymenttransaction_conditions.append(
                PaymentTransactions.created_at <= end_date.replace(tzinfo=None)
            )

        failed_stmt = (
            select(func.coalesce(func.count(PaymentTransactions.id), 0))
            .select_from(PaymentTransactions)
            .join(Providers, PaymentTransactions.provider_id == Providers.id)
            .where(
                Providers.code == "albatal",
                *fail_paymenttransaction_conditions,
            )
        )
        failed_row = db.execute(failed_stmt).scalar() or 0

        # Albatal success payment count and fee calculation
        success_paymenttransaction_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
        ]
        if start_date is not None:
            success_paymenttransaction_conditions.append(
                Payments.paid_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            success_paymenttransaction_conditions.append(
                Payments.paid_at <= end_date.replace(tzinfo=None)
            )

        fee_per_payment = func.round(
            func.round(Payments.payment_amount * 0.082, 3) + 50, 3
        )
        fee_per_payment_transaction_fee_excluding = func.round(
            Payments.payment_amount * 0.082, 3
        )

        success_stmt = (
            select(
                func.coalesce(
                    func.sum(fee_per_payment),
                    0,
                ).label("total_transaction_fee"),
                func.coalesce(
                    func.sum(fee_per_payment_transaction_fee_excluding),
                    0,
                ).label("total_payment_transaction_fee_excluding"),
                func.coalesce(
                    func.count(Payments.id),
                    0,
                ).label("successful_payment_transaction_count"),
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == "albatal",
                *success_paymenttransaction_conditions,
            )
        )
        success_row = db.execute(success_stmt).one()
        total_transaction_count = success_row.successful_payment_transaction_count + failed_row
        total_payment_transaction_fee = float(
            success_row.total_transaction_fee + 10000
        )
        return {
            "success_payment_transaction_fee": success_row.total_transaction_fee,
            "success_payment_transaction_count": total_transaction_count,
            "total_payment_transaction_fee": total_payment_transaction_fee,
            "total_payment_transaction_fee_excluding": success_row.total_payment_transaction_fee_excluding,
        }
    except Exception as e:
        logger.error(f"Error getting albatal payment transactions period reports: {e}")
        return None


def get_albatal_income_period_report(
    db: Session,
    now_utc: datetime,
) -> Optional[dict]:
    try:
        # Convert to JST for checking payment cycle date
        now_jst = now_utc + timedelta(hours=9)

        # Determine payment cycle and target period
        if now_jst.day < 15:
            # Payment on 15th (next month): target period is previous month 16~end
            payment_cycle_date = 15
            response_period_start = 16
            response_period_end = None  # Will be calculated (last day of month)
            target_period_start = 16
            target_period_end = None  # Will be calculated (last day of month)

            # Calculate target month (previous month)
            if now_utc.month == 1:
                target_year = now_utc.year - 1
                target_month = 12
            else:
                target_year = now_utc.year
                target_month = now_utc.month - 1

            # For response display - same as target month for 15th payment
            response_month = target_month
        else:
            # Payment on end of month: target period is previous month 16~end
            payment_cycle_date = "末日"
            response_period_start = 16
            response_period_end = None  # Will be calculated (last day of month)
            target_period_start = 16
            target_period_end = None  # Will be calculated (last day of month)

            # Previous month (for sales data calculation - the actual sales month for end-of-month payment)
            if now_utc.month == 1:
                target_year = now_utc.year - 1
                target_month = 12
            else:
                target_year = now_utc.year
                target_month = now_utc.month - 1

            # For response display - same as target month
            response_month = target_month

        # Calculate corresponding period 6 months prior
        # For 16~end period: December (12) -> July (7), January (1) -> August (8), etc.
        # This represents the deposition data from 6 months back
        six_months_ago_month = target_month - 5
        if six_months_ago_month <= 0:
            six_months_ago_month += 12
            six_months_ago_year = target_year - 1
        else:
            six_months_ago_year = target_year

        # Calculate date ranges for target month period
        if target_period_end is None:
            # Last day of month
            if target_month == 12:
                target_period_end_date = datetime(target_year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc) - timedelta(hours=9)
            else:
                target_period_end_date = (datetime(target_year, target_month + 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(microseconds=1)) - timedelta(hours=9)
        else:
            target_period_end_date = datetime(target_year, target_month, target_period_end, 23, 59, 59, 999999, tzinfo=timezone.utc) - timedelta(hours=9)

        target_period_start_date = datetime(target_year, target_month, target_period_start, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(hours=9)

        # Query for target month period
        target_month_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
            Payments.paid_at >= target_period_start_date.replace(tzinfo=None),
            Payments.paid_at <= target_period_end_date.replace(tzinfo=None),
        ]

        target_month_stmt = (
            select(
                func.coalesce(func.sum(Payments.payment_amount), 0).label("total_amount")
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == "albatal",
                *target_month_conditions,
            )
        )

        target_month_amount = float(db.execute(target_month_stmt).scalar() or 0)
        income_90_percent = round(target_month_amount * 0.9, 3)

        # Set start date for 6 months ago period
        # Use the corresponding period based on current JST day
        if now_jst.day < 15:
            # If current day is 1-14, use 1-15 in 6 months ago
            six_months_ago_period_start = 1
            six_months_ago_period_end = 15
        else:
            # If current day is 15+, use 16-end of month in 6 months ago
            six_months_ago_period_start = 16
            six_months_ago_period_end = None

        # Set end date for 6 months ago period
        if six_months_ago_period_end is None:
            # Last day of month
            if six_months_ago_month == 12:
                six_months_ago_end_date = datetime(six_months_ago_year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc) - timedelta(hours=9)
            else:
                six_months_ago_end_date = (datetime(six_months_ago_year, six_months_ago_month + 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(microseconds=1)) - timedelta(hours=9)
        else:
            six_months_ago_end_date = datetime(six_months_ago_year, six_months_ago_month, six_months_ago_period_end, 23, 59, 59, 999999, tzinfo=timezone.utc) - timedelta(hours=9)

        six_months_ago_start_date = datetime(six_months_ago_year, six_months_ago_month, six_months_ago_period_start, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(hours=9)

        # Query for 6 months ago period
        six_months_ago_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
            Payments.paid_at >= six_months_ago_start_date.replace(tzinfo=None),
            Payments.paid_at <= six_months_ago_end_date.replace(tzinfo=None),
        ]

        six_months_ago_stmt = (
            select(
                func.coalesce(func.sum(Payments.payment_amount), 0).label("total_amount")
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == "albatal",
                *six_months_ago_conditions,
            )
        )

        six_months_ago_amount = float(db.execute(six_months_ago_stmt).scalar() or 0)
        income_10_percent = round(six_months_ago_amount * 0.1, 3)

        # Calculate total income
        total_income = round(income_90_percent + income_10_percent, 3)

        # Determine response month (for display on frontend)
        if payment_cycle_date == "末日":
            # End-of-month payment: show previous month (12月16～末日)
            response_display_month = response_month
        else:
            # 15th payment: show target month (previous month 16～end)
            response_display_month = target_month

        return {
            "this_month": now_utc.month,
            "previous_month": response_display_month,
            "payment_cycle_date": payment_cycle_date,
            "total_income": total_income,
            "income_90_percent": income_90_percent,
            "income_10_percent": income_10_percent,
            "target_period_start": response_period_start,
            "target_period_end": response_period_end if response_period_end is not None else "末日",
        }
    except Exception as e:
        logger.error(f"Error getting albatal income report: {e}")
        return None


def get_albatal_consolidated_monthly_income_report(
    db: Session,
    target_year: int,
    target_month: int,
) -> Optional[dict]:
    """Calculate total albatal income for a specific month (both payment cycles)"""
    try:
        # Calculate 6 months ago
        if target_month <= 6:
            six_months_ago_year = target_year - 1
            six_months_ago_month = target_month + 6
        else:
            six_months_ago_year = target_year
            six_months_ago_month = target_month - 6

        # Period 1: target_month 1~15
        period1_start = datetime(target_year, target_month, 1, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(hours=9)
        period1_end = datetime(target_year, target_month, 15, 23, 59, 59, 999999, tzinfo=timezone.utc) - timedelta(hours=9)

        period1_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
            Payments.paid_at >= period1_start.replace(tzinfo=None),
            Payments.paid_at <= period1_end.replace(tzinfo=None),
        ]

        period1_stmt = (
            select(
                func.coalesce(func.sum(Payments.payment_amount), 0).label("total_amount")
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == "albatal",
                *period1_conditions,
            )
        )
        period1_amount = float(db.execute(period1_stmt).scalar() or 0)

        # Period 2: target_month-1 16~end of month
        if target_month == 1:
            prev_year = target_year - 1
            prev_month = 12
        else:
            prev_year = target_year
            prev_month = target_month - 1

        period2_start = datetime(prev_year, prev_month, 16, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(hours=9)

        if prev_month == 12:
            period2_end = datetime(prev_year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc) - timedelta(hours=9)
        else:
            period2_end = (datetime(prev_year, prev_month + 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(microseconds=1)) - timedelta(hours=9)

        period2_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
            Payments.paid_at >= period2_start.replace(tzinfo=None),
            Payments.paid_at <= period2_end.replace(tzinfo=None),
        ]

        period2_stmt = (
            select(
                func.coalesce(func.sum(Payments.payment_amount), 0).label("total_amount")
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == "albatal",
                *period2_conditions,
            )
        )
        period2_amount = float(db.execute(period2_stmt).scalar() or 0)

        # Period 1 (90% + 10%): target_month 1~15
        period1_90_percent = round(period1_amount * 0.9, 3)

        # 6 months ago - 1~15
        if six_months_ago_month <= 6:
            six_months_before_year = six_months_ago_year - 1
            six_months_before_month = six_months_ago_month + 6
        else:
            six_months_before_year = six_months_ago_year
            six_months_before_month = six_months_ago_month - 6

        period1_six_months_start = datetime(six_months_ago_year, six_months_ago_month, 1, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(hours=9)
        period1_six_months_end = datetime(six_months_ago_year, six_months_ago_month, 15, 23, 59, 59, 999999, tzinfo=timezone.utc) - timedelta(hours=9)

        period1_six_months_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
            Payments.paid_at >= period1_six_months_start.replace(tzinfo=None),
            Payments.paid_at <= period1_six_months_end.replace(tzinfo=None),
        ]

        period1_six_months_stmt = (
            select(
                func.coalesce(func.sum(Payments.payment_amount), 0).label("total_amount")
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == "albatal",
                *period1_six_months_conditions,
            )
        )
        period1_six_months_amount = float(db.execute(period1_six_months_stmt).scalar() or 0)
        period1_10_percent = round(period1_six_months_amount * 0.1, 3)

        period1_total = round(period1_90_percent + period1_10_percent, 3)

        # Period 2 (90% + 10%): prev_month 16~end
        period2_90_percent = round(period2_amount * 0.9, 3)

        # 6 months ago - 16~end
        if prev_month == 1:
            period2_six_months_year = prev_year - 1
            period2_six_months_month = 12
        else:
            period2_six_months_year = prev_year
            period2_six_months_month = prev_month - 6 if prev_month > 6 else prev_month + 6

        period2_six_months_start = datetime(period2_six_months_year, period2_six_months_month, 16, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(hours=9)

        if period2_six_months_month == 12:
            period2_six_months_end = datetime(period2_six_months_year, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc) - timedelta(hours=9)
        else:
            period2_six_months_end = (datetime(period2_six_months_year, period2_six_months_month + 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc) - timedelta(microseconds=1)) - timedelta(hours=9)

        period2_six_months_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.payment_price > 0,
            Payments.paid_at >= period2_six_months_start.replace(tzinfo=None),
            Payments.paid_at <= period2_six_months_end.replace(tzinfo=None),
        ]

        period2_six_months_stmt = (
            select(
                func.coalesce(func.sum(Payments.payment_amount), 0).label("total_amount")
            )
            .select_from(Payments)
            .join(Providers, Payments.provider_id == Providers.id)
            .where(
                Providers.code == "albatal",
                *period2_six_months_conditions,
            )
        )
        period2_six_months_amount = float(db.execute(period2_six_months_stmt).scalar() or 0)
        period2_10_percent = round(period2_six_months_amount * 0.1, 3)

        period2_total = round(period2_90_percent + period2_10_percent, 3)

        # Monthly total
        monthly_total_income = round(period1_total + period2_total, 3)

        return {
            "monthly_total_income": monthly_total_income,
            "period1_total": period1_total,  # 1~15 cycle income
            "period2_total": period2_total,  # 16~end cycle income
        }
    except Exception as e:
        logger.error(f"Error getting albatal consolidated monthly income report: {e}")
        return None
