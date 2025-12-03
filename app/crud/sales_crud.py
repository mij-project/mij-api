from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from uuid import UUID
from app.constants.enums import AccountType, PaymentStatus, PaymentType, WithdrawStatus
from app.core.logger import Logger
from sqlalchemy import func, or_, select, case, cast, and_
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from app.models import Creators, Payments, Profiles, Users, Withdraws, Prices, Plans

logger = Logger.get_logger()


def get_sales_summary_by_creator(db: Session, user_id: UUID) -> dict:
    """
    ユーザーの売上概要を取得
    """
    try:
        platform_fee = __get_platform_fee_by_creator(db, user_id)

        payments_stmt = select(
            func.coalesce(func.sum(Payments.payment_price), 0).label(
                "cumulative_sales"
            ),
        ).where(
            Payments.seller_user_id == user_id,
            Payments.status == PaymentStatus.SUCCEEDED,  # succeeded
        )

        payments_result = db.execute(payments_stmt)
        payments_row = payments_result.one()
        cumulative_sales = int(payments_row.cumulative_sales or 0)
        # 手数料を引く
        cumulative_sales_after_platform_fee = cumulative_sales - round(
            cumulative_sales * platform_fee / 100
        )

        withdraws_stmt = select(
            func.coalesce(func.sum(Withdraws.withdraw_amount), 0).label(
                "total_withdraw"
            ),
        ).where(
            Withdraws.user_id == user_id,
            Withdraws.status == WithdrawStatus.COMPLETED,  # completed
        )

        withdraws_result = db.execute(withdraws_stmt)
        withdraws_row = withdraws_result.one()
        total_withdraw = int(withdraws_row.total_withdraw or 0)

        withdrawable_amount = max(
            cumulative_sales_after_platform_fee - total_withdraw, 0
        )

        return {
            "cumulative_sales": cumulative_sales_after_platform_fee,
            "withdrawable_amount": withdrawable_amount,
        }

    except Exception as e:
        logger.error(f"Salesエラーが発生しました: {e}")
        return None


def __get_platform_fee_by_creator(db: Session, user_id: UUID) -> int:
    """
    手数料を計算
    """
    creator = db.query(Creators).filter(Creators.user_id == user_id).first()
    return creator.platform_fee_percent or 10


def get_sales_period_by_creator(
    db: Session,
    user_id: UUID,
    start_date: datetime,
    end_date: datetime,
    previous_start_date: datetime,
    previous_end_date: datetime,
) -> dict:
    """
    売上期間を取得
    """
    try:
        platform_fee = __get_platform_fee_by_creator(db, user_id)

        base_filter = (
            (Payments.seller_user_id == user_id)
            & (Payments.status == PaymentStatus.SUCCEEDED)
            & (Payments.paid_at >= start_date.replace(tzinfo=None))
            & (Payments.paid_at <= end_date.replace(tzinfo=None))
        )

        payments_stmt = select(
            func.coalesce(func.sum(Payments.payment_price), 0).label(
                "cumulative_sales"
            ),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Payments.payment_type == PaymentType.SINGLE,
                            Payments.payment_price,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("single_sales"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            Payments.payment_type == PaymentType.PLAN,
                            Payments.payment_price,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("plan_sales"),
        ).where(base_filter)

        payments_row = db.execute(payments_stmt).one()

        cumulative_sales = int(payments_row.cumulative_sales or 0)
        single_sales = int(payments_row.single_sales or 0)
        plan_sales = int(payments_row.plan_sales or 0)
        cumulative_sales_after_platform_fee = cumulative_sales - round(
            cumulative_sales * platform_fee / 100
        )
        single_sales_after_platform_fee = single_sales - round(
            single_sales * platform_fee / 100
        )
        plan_sales_after_platform_fee = plan_sales - round(
            plan_sales * platform_fee / 100
        )

        previous_payments_stmt = select(
            func.coalesce(func.sum(Payments.payment_price), 0).label(
                "cumulative_sales"
            ),
        ).where(
            Payments.seller_user_id == user_id,
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.created_at >= previous_start_date.replace(tzinfo=None),
            Payments.created_at <= previous_end_date.replace(tzinfo=None),
        )
        previous_payments_row = db.execute(previous_payments_stmt).one()
        previous_cumulative_sales = int(previous_payments_row.cumulative_sales or 0)
        previous_cumulative_sales_after_platform_fee = (
            previous_cumulative_sales
            - round(previous_cumulative_sales * platform_fee / 100)
        )

        return {
            "period_sales": cumulative_sales_after_platform_fee,
            "single_item_sales": single_sales_after_platform_fee,
            "plan_sales": plan_sales_after_platform_fee,
            "previous_period_sales": previous_cumulative_sales_after_platform_fee,
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
                    Payments.order_type == 2,
                    cast(Payments.order_id, PG_UUID) == Prices.id,
                ),
            )
            .outerjoin(
                Plans,
                and_(
                    Payments.order_type == 1,
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
            payments.append(
                {
                    "id": row.Payments.id,
                    "payment_price": row.Payments.payment_price,
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
    """
    try:
        start_naive = start_date.replace(tzinfo=None)
        end_naive = end_date.replace(tzinfo=None)
        start_of_month, end_of_month = __get_in_month_period()
        total_creators = (
            db.query(Users).filter(Users.role == AccountType.CREATOR).count()
        )
        # ---- subquery GMV (lifetime) ----
        total_sales_subq = (
            select(
                Payments.seller_user_id.label("seller_id"),
                func.coalesce(func.sum(Payments.payment_price), 0).label("total_sales"),
            )
            .where(Payments.status == PaymentStatus.SUCCEEDED)
            .group_by(Payments.seller_user_id)
            .subquery()
        )

        # ---- subquery GMV + count in period ----
        period_sales_subq = (
            select(
                Payments.seller_user_id.label("seller_id"),
                func.coalesce(func.sum(Payments.payment_price), 0).label(
                    "period_sales"
                ),
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

        # ---- subquery GMV + count in period ----
        this_month_period_sales_subq = (
            select(
                Payments.seller_user_id.label("seller_id"),
                func.coalesce(func.sum(Payments.payment_price), 0).label(
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

        # --- subquery withdraw amount in period ---
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

        # --- subquery withdraw count in period ---
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

        # base select
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
        else:  # NEWEST
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
                "total_sales": row.total_sales,
                "period_sales": row.period_sales,
                "this_month_period_sales": row.this_month_period_sales,
                "withdrawal_count": row.withdrawal_count,
                "withdrawn_total": row.withdrawn_total,
            }
            creator["un_transfer_total"] = (
                creator["total_sales"] - creator["withdrawn_total"]
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
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_of_month = start_of_month + timedelta(days=30)
    start_of_month = start_of_month.replace(tzinfo=None)
    end_of_month = end_of_month.replace(tzinfo=None)
    return start_of_month, end_of_month
