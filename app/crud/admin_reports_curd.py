from datetime import datetime
import math
from typing import Optional

from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from app.constants.enums import PaymentStatus, PaymentType, WithdrawStatus
from app.core.logger import Logger
from app.models import CompanyUsers, Payments, Withdraws
from app.models.payment_transactions import PaymentTransactions
from app.models.providers import Providers

logger = Logger.get_logger()


def get_gmv_overalltime_report(db: Session) -> Optional[dict]:
    try:
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
            # Plan GMV in period
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            # & (Payments.payment_type == PaymentType.PLAN),
                            & (Payments.payment_type == 2),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_gmv_period"),
            # Single GMV in period
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            # & (Payments.payment_type == PaymentType.SINGLE),
                            & (Payments.payment_type == 1),
                            Payments.payment_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_gmv_period"),
            # Plan COUNT in period
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            # & (Payments.payment_type == PaymentType.PLAN),
                            & (Payments.payment_type == 2),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_count_period"),
            # Single COUNT in period
            func.coalesce(
                func.sum(
                    case(
                        (
                            (Payments.status == PaymentStatus.SUCCEEDED)
                            # & (Payments.payment_type == PaymentType.SINGLE),
                            & (Payments.payment_type == 1),
                            1,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_count_period"),
        ).where(*conditions)

        row = db.execute(stmt).one()

        return {
            "gmv_period": row.gmv_period,
            "plan_gmv_period": row.plan_gmv_period,
            "single_gmv_period": row.single_gmv_period,
            "plan_count_period": row.plan_count_period,
            "single_count_period": row.single_count_period,
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
