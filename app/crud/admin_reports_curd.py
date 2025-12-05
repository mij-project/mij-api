from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, case
from sqlalchemy.orm import Session

from app.constants.enums import PaymentStatus, PaymentType, WithdrawStatus
from app.core.logger import Logger
from app.models import CompanyUsers, Payments, Withdraws
from app.models.payment_transactions import PaymentTransactions

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
                            Payments.payment_price,
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
                            Payments.payment_price,
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
                            Payments.payment_price,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_gmv_overalltime"),
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
        )

        row = db.execute(stmt).one()

        return {
            "gmv_overalltime": row.gmv_overalltime,
            "plan_gmv_overalltime": row.plan_gmv_overalltime,
            "single_gmv_overalltime": row.single_gmv_overalltime,
            "plan_count_overalltime": row.plan_count_overalltime,
            "single_count_overalltime": row.single_count_overalltime,
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
                            Payments.payment_price,
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
                            & (Payments.payment_type == PaymentType.PLAN),
                            Payments.payment_price,
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
                            & (Payments.payment_type == PaymentType.SINGLE),
                            Payments.payment_price,
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
                            & (Payments.payment_type == PaymentType.PLAN),
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
                            & (Payments.payment_type == PaymentType.SINGLE),
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
        conditions_payments = [Payments.status == PaymentStatus.SUCCEEDED]
        if start_date is not None:
            conditions_payments.append(
                Payments.paid_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            conditions_payments.append(
                Payments.paid_at <= end_date.replace(tzinfo=None)
            )

        company_fee_percent = func.coalesce(CompanyUsers.company_fee_percent, 0)

        platform_fee_per_payment = func.round(
            Payments.payment_price * Payments.platform_fee / 100.0
        )
        company_fee_per_payment = func.round(
            platform_fee_per_payment * company_fee_percent / 100.0
        )

        card_fee_per_payment = func.round(Payments.payment_amount * 0.077) + 55

        margin_per_payment = (
            Payments.payment_amount - Payments.payment_price - card_fee_per_payment
        )

        payments_stmt = (
            select(
                func.coalesce(
                    func.sum(platform_fee_per_payment),
                    0,
                ).label("total_platform_fee_gross"),
                func.coalesce(
                    func.sum(company_fee_per_payment),
                    0,
                ).label("total_company_fee"),
                func.coalesce(
                    func.sum(platform_fee_per_payment - company_fee_per_payment),
                    0,
                ).label("total_platform_fee_after_company"),
                func.coalesce(
                    func.sum(margin_per_payment),
                    0,
                ).label("total_platform_margin_card_fee"),
            )
            .select_from(Payments)
            .outerjoin(
                CompanyUsers,
                CompanyUsers.user_id == Payments.seller_user_id,
            )
            .where(*conditions_payments)
        )
        payments_row = db.execute(payments_stmt).one()

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

        failed_stmt = select(
            func.coalesce(func.count(PaymentTransactions.id), 0)
        ).where(*fail_paymenttransaction_conditions)
        failed_row = db.execute(failed_stmt).scalar() or 0

        total_platform_fee_gross = payments_row.total_platform_fee_after_company - (
            failed_row * 44
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

        total_platform_fee_gross = total_platform_fee_gross + (
            approved_withdraw_count * 187
        )

        return {
            "total_platform_fee_gross": total_platform_fee_gross,
            "total_platform_margin_card_fee": payments_row.total_platform_margin_card_fee,
            "approved_withdraw_count": approved_withdraw_count,
            "withdraws_approved_profit": approved_withdraw_count * 187,
        }
    except Exception as e:
        logger.error(f"Error getting revenue overalltime reports: {e}")
        return None


def get_payment_transactions_period_report(
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

        failed_stmt = select(
            func.coalesce(func.count(PaymentTransactions.id), 0)
        ).where(*fail_paymenttransaction_conditions)
        failed_row = db.execute(failed_stmt).scalar() or 0
        # Success payment count
        success_paymenttransaction_conditions = [
            Payments.status == PaymentStatus.SUCCEEDED
        ]
        if start_date is not None:
            success_paymenttransaction_conditions.append(
                Payments.paid_at >= start_date.replace(tzinfo=None)
            )
        if end_date is not None:
            success_paymenttransaction_conditions.append(
                Payments.paid_at <= end_date.replace(tzinfo=None)
            )
        fee_per_payment = (Payments.payment_amount * 0.077) + 55
        fee_per_payment_transaction_fee_excluding = Payments.payment_amount * 0.077
        success_stmt = select(
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
        ).where(*success_paymenttransaction_conditions)
        success_row = db.execute(success_stmt).one()
        total_payment_transaction_fee = (
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

        gmv_in_period_report = get_gmv_period_report(db, start_date, end_date)
        if gmv_in_period_report is None:
            return None
        total_withdraws = withdraws_in_period_row.total_withdraws or 0
        total_gmv = gmv_in_period_report["gmv_period"]
        untransferred_amount_in_period = total_gmv - total_withdraws

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

        gmv_overalltime_report = get_gmv_overalltime_report(db)
        if gmv_overalltime_report is None:
            return None
        total_gmv_overalltime = gmv_overalltime_report["gmv_overalltime"] or 0

        untransferred_amount_overalltime = total_gmv_overalltime - (
            withdraws_overalltime_row.total_withdraws or 0
        )

        return {
            "untransferred_amount_in_period": untransferred_amount_in_period,
            "untransferred_amount_overalltime": untransferred_amount_overalltime,
        }
    except Exception as e:
        logger.error(f"Error getting untransferred amount period reports: {e}")
        return None
