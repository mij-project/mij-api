from datetime import datetime, timedelta, timezone
import math
from typing import Optional
from sqlalchemy.orm import Session
from uuid import UUID
from app.constants.enums import AccountType, PaymentStatus, WithdrawStatus
from app.core.logger import Logger
from sqlalchemy import func, or_, select, case, cast, and_
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models import (
    Banks,
    Creators,
    Payments,
    Profiles,
    UserBanks,
    Users,
    Withdraws,
    Prices,
    Plans,
)
from app.schemas.withdraw import WithdrawalApplicationRequest

logger = Logger.get_logger()


def get_sales_summary_by_creator(db: Session, user_id: UUID) -> dict:
    """
    ユーザーの売上概要を取得
    """
    try:
        fee_per_payment = func.ceil(
            Payments.payment_price * Payments.platform_fee / 100.0
        )
        net_per_payment = Payments.payment_price - fee_per_payment
        payments_stmt = select(
            func.coalesce(
                func.sum(net_per_payment),
                0,
            ).label("cumulative_sales_after_platform_fee")
        ).where(
            Payments.seller_user_id == user_id,
            Payments.status.in_([PaymentStatus.SUCCEEDED]),
        )
        payments_result = db.execute(payments_stmt)
        payments_row = payments_result.one()
        cumulative_sales_after_platform_fee = int(
            payments_row.cumulative_sales_after_platform_fee or 0
        )

        withdraws_stmt = select(
            func.coalesce(func.sum(Withdraws.withdraw_amount), 0).label(
                "total_withdraw"
            ),
        ).where(
            Withdraws.user_id == user_id,
            Withdraws.status.in_(
                [
                    WithdrawStatus.COMPLETED,
                    WithdrawStatus.PROCESSING,
                    WithdrawStatus.PENDING,
                ]
            ),  # completed
        )

        withdraws_result = db.execute(withdraws_stmt)
        withdraws_row = withdraws_result.one()
        total_withdraw = int(withdraws_row.total_withdraw or 0)
        withdrawable_amount = max(
            cumulative_sales_after_platform_fee - total_withdraw, 0
        )

        return {
            "cumulative_sales": withdrawable_amount,
            "withdrawable_amount": withdrawable_amount,
        }

    except Exception as e:
        logger.error(f"Salesエラーが発生しました: {e}")
        return None


def get_sales_period_by_creator(
    db: Session,
    user_id: UUID,
    start_date: datetime,
    end_date: datetime,
    previous_start_date: datetime,
    previous_end_date: datetime,
) -> Optional[dict]:
    """
    売上期間を取得（クリエイターごと）
    - period_sales: 期間中の合計売上（プラットフォーム手数料差引後）
    - single_item_sales: 期間中の単品売上（手数料差引後）
    - plan_sales: 期間中のサブスク売上（手数料差引後）
    - previous_period_sales: 前期間の合計売上（手数料差引後）
    """

    try:
        # 時刻をDBの型（naive）に合わせる
        start_naive = start_date.replace(tzinfo=None)
        end_naive = end_date.replace(tzinfo=None)
        prev_start_naive = previous_start_date.replace(tzinfo=None)
        prev_end_naive = previous_end_date.replace(tzinfo=None)

        # 1. 定義: 1レコードあたりの手数料 & ネット売上
        # fee_per_payment = ceil(payment_price * platform_fee / 100)
        fee_per_payment = func.ceil(
            Payments.payment_price * Payments.platform_fee / 100.0,
        )
        net_per_payment = Payments.payment_price - fee_per_payment

        # 2. 今期間の売上（net）
        base_filter_current = (
            (Payments.seller_user_id == user_id)
            & (Payments.status == PaymentStatus.SUCCEEDED)
            & (Payments.paid_at >= start_naive)
            & (Payments.paid_at <= end_naive)
        )

        payments_stmt = select(
            # 期間中の合計売上（手数料差引後）
            func.coalesce(
                func.sum(net_per_payment),
                0,
            ).label("period_sales"),
            # 単品売上（手数料差引後）
            func.coalesce(
                func.sum(
                    case(
                        (
                            # Payments.payment_type == PaymentType.SINGLE,
                            Payments.payment_type == 1,
                            net_per_payment,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_item_sales"),
            # サブスク売上（手数料差引後）
            func.coalesce(
                func.sum(
                    case(
                        (
                            # Payments.payment_type == PaymentType.PLAN,
                            Payments.payment_type == 2,
                            net_per_payment,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_sales"),
        ).where(base_filter_current)

        payments_row = db.execute(payments_stmt).one()

        period_sales = int(payments_row.period_sales or 0)
        single_item_sales = int(payments_row.single_item_sales or 0)
        plan_sales = int(payments_row.plan_sales or 0)

        # 3. 前期間の売上（net）
        base_filter_previous = (
            (Payments.seller_user_id == user_id)
            & (Payments.status == PaymentStatus.SUCCEEDED)
            & (Payments.paid_at >= prev_start_naive)
            & (Payments.paid_at <= prev_end_naive)
        )

        previous_stmt = select(
            func.coalesce(
                func.sum(net_per_payment),
                0,
            ).label("previous_period_sales"),
        ).where(base_filter_previous)

        previous_row = db.execute(previous_stmt).one()
        previous_period_sales = int(previous_row.previous_period_sales or 0)

        return {
            "period_sales": period_sales,
            "single_item_sales": single_item_sales,
            "plan_sales": plan_sales,
            "previous_period_sales": previous_period_sales,
        }

    except Exception as e:
        logger.exception(f"Sales period error: {e}")
        return None


def get_sales_history_by_creator(
    db: Session,
    user_id: UUID,
    start_date: datetime,
    end_date: datetime,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """
    売上履歴を取得
    """
    try:
        payments_query = (
            select(
                Payments,
                Profiles.username.label("buyer_username"),
                Prices.post_id.label("single_post_id"),
                Plans.id.label("plan_id"),
                Plans.name.label("plan_name"),
            )
            .join(Profiles, Profiles.user_id == Payments.buyer_user_id)
            .outerjoin(
                Prices,
                and_(
                    Payments.order_type == 1,
                    cast(Payments.order_id, PG_UUID) == Prices.id,
                ),
            )
            .outerjoin(
                Plans,
                and_(
                    Payments.order_type == 2,
                    cast(Payments.order_id, PG_UUID) == Plans.id,
                ),
            )
            .where(
                Payments.seller_user_id == user_id,
                Payments.status == PaymentStatus.SUCCEEDED,
                Payments.paid_at >= start_date.replace(tzinfo=None),
                Payments.paid_at <= end_date.replace(tzinfo=None),
            )
            .order_by(Payments.paid_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
        )

        count_query = select(func.count()).select_from(
            select(Payments)
            .where(
                Payments.seller_user_id == user_id,
                Payments.status == PaymentStatus.SUCCEEDED,
                Payments.paid_at >= start_date.replace(tzinfo=None),
                Payments.paid_at <= end_date.replace(tzinfo=None),
            )
            .subquery()
        )

        total = db.execute(count_query).scalar() or 0
        rows = db.execute(payments_query).all()
        payments = []
        for row in rows:
            fee_per_payment = math.ceil(
                row.Payments.payment_price * row.Payments.platform_fee / 100.0
            )
            net_per_payment = row.Payments.payment_price - fee_per_payment
            payments.append(
                {
                    "id": row.Payments.id,
                    "payment_price": net_per_payment,
                    "payment_type": row.Payments.payment_type,
                    "paid_at": row.Payments.paid_at,
                    "buyer_username": row.buyer_username,
                    "single_post_id": row.single_post_id,
                    "plan_id": row.plan_id,
                    "plan_name": row.plan_name,
                }
            )
        return {
            "payments": payments,
            "total": total,
            "page": page,
            "limit": limit,
        }
    except Exception as e:
        logger.exception(f"Sales history error: {e}")
        return None


def get_creators_sales_by_period(
    db: Session,
    start_date: datetime,
    end_date: datetime,
    page: int = 1,
    limit: int = 20,
    search: str = None,
    sort: str = "newest",
) -> dict:
    """
    クリエイターの売上を取得
    - total_sales, period_sales, this_month_period_sales は
      各決済ごとのプラットフォーム手数料控除後の金額で集計
    """
    try:
        start_naive = start_date.replace(tzinfo=None)
        end_naive = end_date.replace(tzinfo=None)
        start_of_month, end_of_month = __get_in_month_period()

        total_creators = (
            db.query(Users).filter(Users.role == AccountType.CREATOR).count()
        )

        # ----- 1. per-payment: fee & net amount -----
        # fee_per_payment = ceil(payment_price * platform_fee / 100)
        fee_per_payment = func.ceil(
            Payments.payment_price * Payments.platform_fee / 100.0
        )
        # net_per_payment = payment_price - fee
        net_per_payment = Payments.payment_price - fee_per_payment

        # ---- subquery: lifetime net sales (total_sales) ----
        total_sales_subq = (
            select(
                Payments.seller_user_id.label("seller_id"),
                func.coalesce(func.sum(net_per_payment), 0).label("total_sales"),
            )
            .where(Payments.status == PaymentStatus.SUCCEEDED)
            .group_by(Payments.seller_user_id)
            .subquery()
        )

        # ---- subquery: net sales + count in selected period ----
        period_sales_subq = (
            select(
                Payments.seller_user_id.label("seller_id"),
                func.coalesce(func.sum(net_per_payment), 0).label("period_sales"),
                func.count(Payments.id).label("transaction_count"),
            )
            .where(
                Payments.status == PaymentStatus.SUCCEEDED,
                Payments.paid_at >= start_naive,
                Payments.paid_at <= end_naive,
            )
            .group_by(Payments.seller_user_id)
            .subquery()
        )

        # ---- subquery: net sales + count in this month ----
        this_month_period_sales_subq = (
            select(
                Payments.seller_user_id.label("seller_id"),
                func.coalesce(func.sum(net_per_payment), 0).label(
                    "this_month_period_sales"
                ),
                func.count(Payments.id).label("this_month_transaction_count"),
            )
            .where(
                Payments.status == PaymentStatus.SUCCEEDED,
                Payments.paid_at >= start_of_month,
                Payments.paid_at <= end_of_month,
            )
            .group_by(Payments.seller_user_id)
            .subquery()
        )

        # --- subquery: withdraw amount in period ---
        withdrawals_subq = (
            select(
                Withdraws.user_id.label("creator_id"),
                func.coalesce(func.sum(Withdraws.withdraw_amount), 0).label(
                    "withdrawn_total"
                ),
            )
            .where(
                Withdraws.status == WithdrawStatus.COMPLETED,
                Withdraws.created_at >= start_naive,
                Withdraws.created_at <= end_naive,
            )
            .group_by(Withdraws.user_id)
            .subquery()
        )

        # --- subquery: withdraw count (completed/processing/pending) in period ---
        withdrawals_count_subq = (
            select(
                Withdraws.user_id.label("creator_id"),
                func.coalesce(func.count(Withdraws.id), 0).label("withdrawal_count"),
            )
            .where(
                Withdraws.status.in_(
                    [
                        WithdrawStatus.COMPLETED,
                        WithdrawStatus.PROCESSING,
                        WithdrawStatus.PENDING,
                    ]
                ),
                Withdraws.created_at >= start_naive,
                Withdraws.created_at <= end_naive,
            )
            .group_by(Withdraws.user_id)
            .subquery()
        )

        # ----- base select -----
        stmt = (
            select(
                Users.id.label("creator_id"),
                Profiles.username.label("username"),
                Creators.platform_fee_percent.label("platform_fee_rate"),
                func.coalesce(total_sales_subq.c.total_sales, 0).label("total_sales"),
                func.coalesce(period_sales_subq.c.period_sales, 0).label(
                    "period_sales"
                ),
                func.coalesce(
                    this_month_period_sales_subq.c.this_month_period_sales, 0
                ).label("this_month_period_sales"),
                func.coalesce(withdrawals_count_subq.c.withdrawal_count, 0).label(
                    "withdrawal_count"
                ),
                func.coalesce(withdrawals_subq.c.withdrawn_total, 0).label(
                    "withdrawn_total"
                ),
            )
            .select_from(Users)
            .join(Profiles, Profiles.user_id == Users.id)
            .join(Creators, Creators.user_id == Users.id)
            .outerjoin(total_sales_subq, total_sales_subq.c.seller_id == Users.id)
            .outerjoin(period_sales_subq, period_sales_subq.c.seller_id == Users.id)
            .outerjoin(
                this_month_period_sales_subq,
                this_month_period_sales_subq.c.seller_id == Users.id,
            )
            .outerjoin(withdrawals_subq, withdrawals_subq.c.creator_id == Users.id)
            .outerjoin(
                withdrawals_count_subq, withdrawals_count_subq.c.creator_id == Users.id
            )
        )

        conditions = [Users.role == AccountType.CREATOR]

        if search:
            q = search.strip()
            if q:
                pattern = f"%{q}%"
                conditions.append(
                    or_(
                        Profiles.username.ilike(pattern),
                    )
                )

        stmt = stmt.where(*conditions)

        # ---- sort ----
        if sort == "sales_desc":
            order_expr = func.coalesce(total_sales_subq.c.total_sales, 0).desc()
        elif sort == "sales_asc":
            order_expr = func.coalesce(total_sales_subq.c.total_sales, 0).asc()
        elif sort == "name_asc":
            order_expr = Profiles.username.asc().nullslast()
        else:  # newest
            order_expr = Users.created_at.desc()

        stmt = stmt.order_by(order_expr)

        total_found = (
            db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
        )

        stmt = stmt.offset((page - 1) * limit).limit(limit)

        rows = db.execute(stmt).all()

        creators = []

        for row in rows:
            creator = {
                "id": row.creator_id,
                "username": row.username,
                "platform_fee_rate": row.platform_fee_rate,
                # すでにプラットフォーム手数料差引後
                "total_sales": int(row.total_sales or 0),
                "period_sales": int(row.period_sales or 0),
                "this_month_period_sales": int(row.this_month_period_sales or 0),
                "withdrawal_count": int(row.withdrawal_count or 0),
                "withdrawn_total": int(row.withdrawn_total or 0),
            }
            # 未振込残高 = net total_sales - 出金済み/申請中? (ここは仕様次第)
            creator["un_transfer_total"] = max(
                creator["total_sales"] - creator["withdrawn_total"], 0
            )
            creator["platform_fee_rate"] = (
                creator["platform_fee_rate"]
                if creator["platform_fee_rate"] is not None
                else 10
            )
            creators.append(creator)

        return {
            "creators": creators,
            "total_creators": total_creators,
            "total_pages": (total_found + limit - 1) // limit,
        }

    except Exception as e:
        logger.exception(f"Creators sales by period error: {e}")
        return None


def __get_in_month_period():
    now = datetime.now(timezone.utc)
    start_of_month = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(hours=9)
    end_of_month = start_of_month + timedelta(days=30) - timedelta(hours=9)
    start_of_month = start_of_month.replace(tzinfo=None)
    end_of_month = end_of_month.replace(tzinfo=None)
    return start_of_month, end_of_month


def get_latest_withdrawal_application_by_user_id(
    db: Session, user_id: UUID
) -> Withdraws:
    """
    最新の出金申請を取得
    """
    try:
        return (
            db.query(Withdraws)
            .filter(Withdraws.user_id == user_id)
            .order_by(Withdraws.created_at.desc())
            .first()
        )
    except Exception as e:
        logger.exception(f"Latest withdrawal application by user id error: {e}")
        return None


def create_withdrawal_application_by_user_id(
    db: Session,
    user_id: UUID,
    withdrawal_application_request: WithdrawalApplicationRequest,
) -> bool:
    """
    ユーザーの出金申請を作成
    """
    try:
        withdrawal_application = Withdraws(
            user_id=user_id,
            withdraw_amount=withdrawal_application_request.withdraw_amount,
            transfer_amount=withdrawal_application_request.transfer_amount,
            user_bank_id=withdrawal_application_request.user_bank_id,
            status=WithdrawStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(withdrawal_application)
        db.commit()
        return True
    except Exception as e:
        logger.exception(f"Create withdrawal application by user id error: {e}")
        return False


def get_withdrawal_application_histories_by_user_id(
    db: Session, user_id: UUID, page: int = 1, limit: int = 20
) -> dict:
    """
    ユーザーの出金申請履歴を取得
    """
    try:
        offset = (page - 1) * limit
        total_count = db.query(Withdraws).filter(Withdraws.user_id == user_id).count()
        withdrawal_applications_query = (
            db.query(Withdraws)
            .filter(Withdraws.user_id == user_id)
            .order_by(Withdraws.updated_at.desc(), Withdraws.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "withdrawal_applications": withdrawal_applications_query,
            "total_count": total_count,
        }
    except Exception as e:
        logger.exception(f"Withdrawal application histories by user id error: {e}")
        return None


def get_creators_withdraw_summary_by_period_for_admin(
    db: Session,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> dict:
    """
    クリエイターの出金概要を取得
    """
    try:
        # in month transferred summary
        start_of_month, end_of_month = __get_in_month_period()
        in_month_stmt = select(
            func.coalesce(func.sum(Withdraws.transfer_amount), 0).label(
                "in_month_transferred_total"
            ),
            func.coalesce(func.count(Withdraws.id), 0).label(
                "in_month_transferred_count"
            ),
        ).where(
            Withdraws.status.in_([WithdrawStatus.COMPLETED]),
            Withdraws.created_at >= start_of_month,
            Withdraws.created_at <= end_of_month,
        )
        in_month_transferred = db.execute(in_month_stmt).one()
        in_month_transferred_count = in_month_transferred.in_month_transferred_count
        in_month_transferred_total = in_month_transferred.in_month_transferred_total

        # total transferred summary
        summary_transferred_count_stmt = select(
            func.coalesce(func.count(Withdraws.id), 0).label(
                "summary_transferred_count"
            )
        ).where(
            Withdraws.status.in_([WithdrawStatus.COMPLETED]),
        )
        summary_transferred_count_row = db.execute(summary_transferred_count_stmt).one()
        summary_transferred_count = (
            summary_transferred_count_row.summary_transferred_count or 0
        )

        # total transferred summary in period
        total_stmt = select(
            func.coalesce(func.sum(Withdraws.transfer_amount), 0).label(
                "total_transferred_total"
            ),
            func.coalesce(func.count(Withdraws.id), 0).label("total_transferred_count"),
        ).where(
            Withdraws.status.in_([WithdrawStatus.COMPLETED]),
        )

        if start_date and end_date:
            total_stmt = total_stmt.where(
                Withdraws.created_at >= start_date,
                Withdraws.created_at <= end_date,
            )

        total_row = db.execute(total_stmt).one()
        total_transferred_total = total_row.total_transferred_total
        total_transferred_count = total_row.total_transferred_count

        # Count withdrawals need to be processed
        pending_stmt = select(
            func.coalesce(func.count(Withdraws.id), 0).label(
                "withdrawals_need_to_be_processed_count"
            ),
            func.coalesce(func.sum(Withdraws.transfer_amount), 0).label(
                "withdrawals_need_to_be_processed_total"
            ),
        ).where(
            Withdraws.status.in_([WithdrawStatus.PENDING, WithdrawStatus.PROCESSING]),
        )

        pending_row = db.execute(pending_stmt).one()
        withdrawals_need_to_be_processed_count = (
            pending_row.withdrawals_need_to_be_processed_count
        )
        withdrawals_need_to_be_processed_total = (
            pending_row.withdrawals_need_to_be_processed_total
        )

        return {
            "in_month_transferred_total": in_month_transferred_total,
            "in_month_transferred_count": in_month_transferred_count,
            "summary_transferred_count": summary_transferred_count,
            "total_transferred_total": total_transferred_total,
            "total_transferred_count": total_transferred_count,
            "pending_count": withdrawals_need_to_be_processed_count,
            "pending_total": withdrawals_need_to_be_processed_total,
        }
    except Exception as e:
        logger.exception(f"Creators withdraw summary by period error: {e}")
        return None


def get_creators_withdrawals_by_period_for_admin(
    db: Session,
    start_date: datetime,
    end_date: datetime,
    page: int = 1,
    limit: int = 20,
    filter: int = 0,
) -> dict:
    """
    クリエイターの出金を取得
    """
    try:
        offset = (page - 1) * limit
        base_stmt = (
            db.query(
                Withdraws,
                Profiles.username.label("creator_username"),
                UserBanks.account_number.label("account_number"),
                UserBanks.account_holder_name.label("account_holder_name"),
                UserBanks.account_type.label("account_type"),
                Banks.bank_code.label("bank_code"),
                Banks.bank_name.label("bank_name"),
                Banks.branch_name.label("branch_name"),
                Banks.branch_code.label("branch_code"),
            )
            .join(Profiles, Profiles.user_id == Withdraws.user_id)
            .join(UserBanks, UserBanks.id == Withdraws.user_bank_id)
            .join(Banks, UserBanks.bank_id == Banks.id)
        )
        if start_date and end_date:
            base_stmt = base_stmt.filter(
                Withdraws.created_at >= start_date,
                Withdraws.created_at <= end_date,
            )
        if filter != 0:
            base_stmt = base_stmt.filter(Withdraws.status == filter)

        total_count = base_stmt.count()
        total_pages = (total_count + limit - 1) // limit
        base_stmt = base_stmt.order_by(Withdraws.requested_at.desc())
        withdrawals = base_stmt.offset(offset).limit(limit).all()

        return {
            "withdrawals": withdrawals,
            "total_count": total_count,
            "total_pages": total_pages,
            "page": page,
            "limit": limit,
        }

    except Exception as e:
        logger.exception(f"Creators withdrawals by period error: {e}")
        return None


def update_withdrawal_application_status_by_admin(
    db: Session,
    application_id: str,
    status: int,
    admin_id: str,
) -> bool:
    """
    管理者による出金申請ステータスを更新
    """
    try:
        now = datetime.now(timezone.utc)
        withdrawal_application = (
            db.query(Withdraws).filter(Withdraws.id == application_id).first()
        )
        if not withdrawal_application:
            return False
        if status == WithdrawStatus.COMPLETED:
            withdrawal_application.completed_at = now
            withdrawal_application.approved_by = admin_id

        withdrawal_application.processed_at = now
        withdrawal_application.approved_at = now
        withdrawal_application.updated_at = now
        withdrawal_application.status = status
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.exception(f"Update withdrawal application status by admin error: {e}")
        return False


def get_payments_by_user_id(
    db: Session,
    user_id: UUID,
    start_date: datetime,
    end_date: datetime,
    page: int = 1,
    limit: int = 20,
) -> dict:
    """
    ユーザーの決済履歴を取得
    """
    try:
        offset = (page - 1) * limit
        payments_query = (
            select(
                Payments,
                Profiles.username.label("buyer_username"),
                Prices.post_id.label("single_post_id"),
                Plans.id.label("plan_id"),
                Plans.name.label("plan_name"),
            )
            .join(Profiles, Profiles.user_id == Payments.buyer_user_id)
            .outerjoin(
                Prices,
                and_(
                    Payments.order_type == 1,
                    cast(Payments.order_id, PG_UUID) == Prices.id,
                ),
            )
            .outerjoin(
                Plans,
                and_(
                    Payments.order_type == 2,
                    cast(Payments.order_id, PG_UUID) == Plans.id,
                ),
            )
            .where(
                Payments.buyer_user_id == user_id,
                Payments.status == PaymentStatus.SUCCEEDED,
                Payments.paid_at >= start_date.replace(tzinfo=None),
                Payments.paid_at <= end_date.replace(tzinfo=None),
            )
            .order_by(Payments.paid_at.desc())
            .offset(offset)
            .limit(limit)
        )

        count_query = select(func.count()).select_from(
            select(Payments)
            .where(
                Payments.buyer_user_id == user_id,
                Payments.status == PaymentStatus.SUCCEEDED,
                Payments.paid_at >= start_date.replace(tzinfo=None),
                Payments.paid_at <= end_date.replace(tzinfo=None),
            )
            .subquery()
        )
        total = db.execute(count_query).scalar() or 0
        rows = db.execute(payments_query).all()
        total_pages = (total + limit - 1) // limit
        payments = []
        for row in rows:
            payment = {
                "id": row.Payments.id,
                "payment_amount": row.Payments.payment_amount,
                "payment_type": row.Payments.payment_type,
                "payment_status": row.Payments.status,
                "paid_at": row.Payments.paid_at,
                "buyer_username": row.buyer_username,
                "single_post_id": row.single_post_id,
                "plan_id": row.plan_id,
                "plan_name": row.plan_name,
            }
            payments.append(payment)
        return {
            "payments": payments,
            "total": total,
            "total_pages": total_pages,
            "page": page,
            "limit": limit,
            "has_next": (page * limit) < total,
            "has_previous": page > 1,
        }
    except Exception as e:
        logger.exception(f"Get payments by user id error: {e}")
        return None
