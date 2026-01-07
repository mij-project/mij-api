import math
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, case, String, cast, tuple_
from sqlalchemy.orm import Session
from uuid import UUID
from app.constants.enums import PaymentStatus
from app.models import Payments, Plans, Posts, Prices, Users
from app.models.plans import PostPlans
from app.models.time_sale import TimeSale
from app.schemas.post_price_timesale import PriceTimeSaleCreateRequest
from app.schemas.post_plan_timesale import PlanTimeSaleCreateRequest
from app.schemas.post_plan_timesale import UpdateRequest
from app.core.logger import Logger

logger = Logger.get_logger()


def get_price_time_sale_by_post_id(
    db: Session, post_id: UUID, page: int, limit: int
) -> List[TimeSale]:
    """投稿の価格時間販売情報を取得する"""
    offset = (page - 1) * limit
    now = func.now()
    within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)
    base_filters = (
        TimeSale.post_id == post_id,
        TimeSale.price_id.is_not(None),
        TimeSale.deleted_at.is_(None),
    )

    start_bound = TimeSale.start_date
    end_bound = TimeSale.end_date

    purchase_count_sq = (
        select(func.count(Payments.id))
        .where(
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.paid_at.is_not(None),
            Payments.paid_at >= start_bound,
            Payments.paid_at <= end_bound,
            Payments.order_id == cast(TimeSale.price_id, String),
        )
        .correlate(TimeSale)
        .scalar_subquery()
    )

    is_active_expr = case(
        (TimeSale.max_purchase_count.is_(None), within_time),
        else_=and_(within_time, purchase_count_sq < TimeSale.max_purchase_count),
    ).label("is_active")

    is_expired_expr = case(
        (now >= TimeSale.end_date, True),
        (
            and_(
                TimeSale.max_purchase_count.is_not(None),
                within_time,
                purchase_count_sq >= TimeSale.max_purchase_count,
            ),
            True,
        ),
        else_=False,
    ).label("is_expired")

    stmt_items = (
        select(
            TimeSale,
            purchase_count_sq.label("purchase_count"),
            is_active_expr,
            is_expired_expr,
        )
        .where(*base_filters)
        .order_by(TimeSale.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    stmt_total = (
        select(func.count(TimeSale.id)).select_from(TimeSale).where(*base_filters)
    )

    rows = db.execute(stmt_items).all()
    total = db.execute(stmt_total).scalar_one()

    return rows, total


def create_price_time_sale_by_post_id(
    db: Session, post_id: UUID, payload: PriceTimeSaleCreateRequest, current_user: Users
) -> TimeSale:
    """投稿の価格時間販売情報を作成する"""
    try:
        # Check post of current user
        post = (
            db.query(Posts)
            .filter(Posts.id == post_id, Posts.creator_user_id == current_user.id)
            .first()
        )
        if not post:
            return None
        # Check price of post
        price = db.query(Prices).filter(Prices.post_id == post_id).first()
        sale_price = price.price - math.ceil(
            price.price * payload.sale_percentage / 100
        )
        # Create time sale
        time_sale = TimeSale(
            post_id=post_id,
            price_id=price.id,
            start_date=payload.start_date,
            end_date=payload.end_date,
            sale_percentage=payload.sale_percentage,
            sale_price=sale_price,
            max_purchase_count=payload.max_purchase_count,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(time_sale)
        db.commit()
        db.refresh(time_sale)
        return time_sale
    except Exception as e:
        logger.exception(f"Create price time sale error: {e}")
        db.rollback()
        return None


def check_exists_price_time_sale_in_period_by_post_id(
    db: Session,
    post_id: UUID,
    start_date: datetime,
    end_date: datetime,
    time_sale_id: Optional[UUID] = None,
) -> bool:
    """投稿の価格時間販売情報が期間内に存在するかを確認する"""
    is_exists = False
    time_sale = (
        db.query(TimeSale)
        .filter(
            TimeSale.post_id == post_id,
            TimeSale.price_id.is_not(None),
            TimeSale.start_date.is_not(None),
            TimeSale.end_date.is_not(None),
            TimeSale.start_date < end_date.replace(tzinfo=None),
            TimeSale.end_date > start_date.replace(tzinfo=None),
        )
        .first()
    )
    if time_sale is not None:
        is_exists = True
    if (
        time_sale_id is not None
        and time_sale is not None
        and str(time_sale_id) == str(time_sale.id)
    ):
        is_exists = False
    return is_exists


def get_plan_time_sale_by_plan_id(
    db: Session, plan_id: UUID, page: int, limit: int
) -> List[TimeSale]:
    """プランの価格時間販売情報を取得する"""
    offset = (page - 1) * limit
    now = func.now()
    within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)
    base_filters = (
        TimeSale.plan_id == plan_id,
        TimeSale.price_id.is_(None),
        TimeSale.post_id.is_(None),
        TimeSale.deleted_at.is_(None),
    )

    start_bound = TimeSale.start_date
    end_bound = TimeSale.end_date

    purchase_count_sq = (
        select(func.count(Payments.id))
        .where(
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.paid_at.is_not(None),
            Payments.paid_at >= start_bound,
            Payments.paid_at <= end_bound,
            Payments.order_id == cast(TimeSale.plan_id, String),
            Payments.payment_price == TimeSale.sale_price,
        )
        .correlate(TimeSale)
        .scalar_subquery()
    )

    is_active_expr = case(
        (TimeSale.max_purchase_count.is_(None), within_time),
        else_=and_(within_time, purchase_count_sq < TimeSale.max_purchase_count),
    ).label("is_active")

    is_expired_expr = case(
        (now >= TimeSale.end_date, True),
        (
            and_(
                TimeSale.max_purchase_count.is_not(None),
                within_time,
                purchase_count_sq >= TimeSale.max_purchase_count,
            ),
            True,
        ),
        else_=False,
    ).label("is_expired")

    stmt_items = (
        select(
            TimeSale,
            purchase_count_sq.label("purchase_count"),
            is_active_expr,
            is_expired_expr,
        )
        .where(*base_filters)
        .order_by(TimeSale.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    stmt_total = (
        select(func.count(TimeSale.id)).select_from(TimeSale).where(*base_filters)
    )

    rows = db.execute(stmt_items).all()
    total = db.execute(stmt_total).scalar_one()

    return rows, total


def check_exists_plan_time_sale_in_period_by_plan_id(
    db: Session,
    plan_id: UUID,
    start_date: datetime,
    end_date: datetime,
    time_sale_id: Optional[UUID] = None,
) -> bool:
    """投稿の価格時間販売情報が期間内に存在するかを確認する"""
    is_exists = False
    time_sale = (
        db.query(TimeSale)
        .filter(
            TimeSale.plan_id == plan_id,
            TimeSale.price_id.is_(None),
            TimeSale.start_date.is_not(None),
            TimeSale.end_date.is_not(None),
            TimeSale.start_date < end_date.replace(tzinfo=None),
            TimeSale.end_date > start_date.replace(tzinfo=None),
        )
        .first()
    )
    if time_sale is not None:
        is_exists = True
    if (
        time_sale_id is not None
        and time_sale is not None
        and str(time_sale_id) == str(time_sale.id)
    ):
        is_exists = False
    return is_exists


def create_plan_time_sale_by_plan_id(
    db: Session, plan_id: UUID, payload: PlanTimeSaleCreateRequest, current_user: Users
) -> TimeSale:
    """プランの価格時間販売情報を作成する"""
    try:
        plan = db.query(Plans).filter(Plans.id == plan_id).first()
        if not plan:
            return None
        if plan.creator_user_id != current_user.id:
            return None
        sale_price = plan.price - math.ceil(plan.price * payload.sale_percentage / 100)
        # Create time sale
        time_sale = TimeSale(
            plan_id=plan_id,
            price_id=None,
            post_id=None,
            start_date=payload.start_date,
            end_date=payload.end_date,
            sale_percentage=payload.sale_percentage,
            sale_price=sale_price,
            max_purchase_count=payload.max_purchase_count,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(time_sale)
        db.commit()
        db.refresh(time_sale)
        return time_sale
    except Exception as e:
        logger.exception(f"Create plan time sale error: {e}")
        db.rollback()
        return None


def get_active_price_timesale(db: Session, post_id: UUID, price_id: UUID) -> TimeSale:
    """投稿の価格時間販売情報を取得する"""
    now = func.now()
    within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)

    base_filters = (
        TimeSale.post_id == post_id,
        TimeSale.price_id == price_id,
        TimeSale.plan_id.is_(None),
        TimeSale.deleted_at.is_(None),
        TimeSale.start_date.is_not(None),
        TimeSale.end_date.is_not(None),
    )

    start_bound = TimeSale.start_date
    end_bound = TimeSale.end_date

    purchase_count_sq = (
        select(func.count(Payments.id))
        .where(
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.paid_at.is_not(None),
            Payments.paid_at >= start_bound,
            Payments.paid_at <= end_bound,
            Payments.order_id == cast(TimeSale.price_id, String),
            Payments.payment_price == TimeSale.sale_price,
        )
        .correlate(TimeSale)
        .scalar_subquery()
    )

    is_active_expr = case(
        (TimeSale.max_purchase_count.is_(None), within_time),
        else_=and_(within_time, purchase_count_sq < TimeSale.max_purchase_count),
    ).label("is_active")

    is_expired_expr = case(
        (now >= TimeSale.end_date, True),
        (
            and_(
                TimeSale.max_purchase_count.is_not(None),
                within_time,
                purchase_count_sq >= TimeSale.max_purchase_count,
            ),
            True,
        ),
        else_=False,
    ).label("is_expired")

    stmt = (
        select(
            TimeSale,
            purchase_count_sq.label("purchase_count"),
            is_active_expr,
            is_expired_expr,
        )
        .where(*base_filters)
        .order_by(TimeSale.created_at.desc())
    )

    # active だけ取りたい
    row = db.execute(stmt).first()
    if not row:
        return None

    ts, purchase_count, is_active, is_expired = row
    if not is_active:
        return None

    return {
        "id": ts.id,
        "sale_percentage": ts.sale_percentage,
        "start_date": ts.start_date,
        "end_date": ts.end_date,
        "max_purchase_count": ts.max_purchase_count,
        "purchase_count": int(purchase_count) if purchase_count is not None else 0,
        "is_active": bool(is_active),
        "is_expired": bool(is_expired),
    }


def get_active_price_timesale_pairs(
    db: Session, pairs: list[tuple[UUID, UUID]]
) -> set[tuple[str, str]]:
    """
    return set of (post_id, price_id) that has active timesale
    """
    if not pairs:
        return set()

    now = func.now()
    within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)

    base_filters = (
        tuple_(TimeSale.post_id, TimeSale.price_id).in_(pairs),
        TimeSale.plan_id.is_(None),
        TimeSale.deleted_at.is_(None),
        TimeSale.start_date.is_not(None),
        TimeSale.end_date.is_not(None),
    )

    start_bound = TimeSale.start_date
    end_bound = TimeSale.end_date

    purchase_count_sq = (
        select(func.count(Payments.id))
        .where(
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.paid_at.is_not(None),
            Payments.paid_at >= start_bound,
            Payments.paid_at <= end_bound,
            Payments.order_id == cast(TimeSale.price_id, String),
            Payments.payment_price == TimeSale.sale_price,
        )
        .correlate(TimeSale)
        .scalar_subquery()
    )

    active_filter = or_(
        and_(TimeSale.max_purchase_count.is_(None), within_time),
        and_(
            TimeSale.max_purchase_count.is_not(None),
            within_time,
            purchase_count_sq < TimeSale.max_purchase_count,
        ),
    )

    stmt = (
        select(
            TimeSale.post_id,
            TimeSale.price_id,
            TimeSale.sale_percentage,
            TimeSale.end_date,
        )
        .where(*base_filters)
        .where(active_filter)
        .distinct()
    )

    rows = db.execute(stmt).all()
    return {
        (str(post_id), str(price_id), sale_percentage, end_date)
        for post_id, price_id, sale_percentage, end_date in rows
    }


def get_active_plan_timesale_map(db: Session, plan_ids: List[UUID]) -> dict:
    """プランの価格時間販売情報を取得する"""
    if not plan_ids:
        return {}

    now = func.now()

    base_filters = (
        TimeSale.plan_id.in_(plan_ids),
        TimeSale.price_id.is_(None),
        TimeSale.post_id.is_(None),
        TimeSale.deleted_at.is_(None),
        TimeSale.start_date.is_not(None),
        TimeSale.end_date.is_not(None),
    )

    within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)
    start_bound = TimeSale.start_date
    end_bound = TimeSale.end_date

    purchase_count_sq = (
        select(func.count(Payments.id))
        .where(
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.paid_at.is_not(None),
            Payments.paid_at >= start_bound,
            Payments.paid_at <= end_bound,
            Payments.order_id == cast(TimeSale.plan_id, String),
            Payments.payment_price == TimeSale.sale_price,
        )
        .correlate(TimeSale)
        .scalar_subquery()
    )

    active_filter = or_(
        and_(TimeSale.max_purchase_count.is_(None), within_time),
        and_(
            TimeSale.max_purchase_count.is_not(None),
            within_time,
            purchase_count_sq < TimeSale.max_purchase_count,
        ),
    )

    is_active_expr = case(
        (TimeSale.max_purchase_count.is_(None), within_time),
        else_=and_(within_time, purchase_count_sq < TimeSale.max_purchase_count),
    ).label("is_active")

    is_expired_expr = case(
        (now >= TimeSale.end_date, True),
        (
            and_(
                TimeSale.max_purchase_count.is_not(None),
                within_time,
                purchase_count_sq >= TimeSale.max_purchase_count,
            ),
            True,
        ),
        else_=False,
    ).label("is_expired")

    stmt = (
        select(
            TimeSale,
            purchase_count_sq.label("purchase_count"),
            is_active_expr,
            is_expired_expr,
        )
        .where(*base_filters)
        .where(active_filter)
        .order_by(TimeSale.created_at.desc())
    )

    rows = db.execute(stmt).all()

    out = {}
    for ts, purchase_count, is_active, is_expired in rows:
        pid = str(ts.plan_id)
        if pid in out:
            continue
        out[pid] = {
            "id": ts.id,
            "sale_percentage": ts.sale_percentage,
            "start_date": ts.start_date,
            "end_date": ts.end_date,
            "max_purchase_count": ts.max_purchase_count,
            "purchase_count": int(purchase_count) if purchase_count is not None else 0,
            "is_active": bool(is_active),
            "is_expired": bool(is_expired),
        }

    return out


def get_active_plan_timesale(db: Session, plan_id: UUID) -> dict:
    """プランの価格時間販売情報を取得する"""
    now = func.now()

    base_filters = (
        TimeSale.plan_id == plan_id,
        TimeSale.price_id.is_(None),
        TimeSale.post_id.is_(None),
        TimeSale.deleted_at.is_(None),
        TimeSale.start_date.is_not(None),
        TimeSale.end_date.is_not(None),
    )

    within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)
    start_bound = TimeSale.start_date
    end_bound = TimeSale.end_date

    purchase_count_sq = (
        select(func.count(Payments.id))
        .where(
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.paid_at.is_not(None),
            Payments.paid_at >= start_bound,
            Payments.paid_at <= end_bound,
            Payments.order_id == cast(TimeSale.plan_id, String),
            Payments.payment_price == TimeSale.sale_price,
        )
        .correlate(TimeSale)
        .scalar_subquery()
    )

    active_filter = or_(
        and_(TimeSale.max_purchase_count.is_(None), within_time),
        and_(
            TimeSale.max_purchase_count.is_not(None),
            within_time,
            purchase_count_sq < TimeSale.max_purchase_count,
        ),
    )

    is_active_expr = case(
        (TimeSale.max_purchase_count.is_(None), within_time),
        else_=and_(within_time, purchase_count_sq < TimeSale.max_purchase_count),
    ).label("is_active")

    is_expired_expr = case(
        (now >= TimeSale.end_date, True),
        (
            and_(
                TimeSale.max_purchase_count.is_not(None),
                within_time,
                purchase_count_sq >= TimeSale.max_purchase_count,
            ),
            True,
        ),
        else_=False,
    ).label("is_expired")

    stmt = (
        select(
            TimeSale,
            purchase_count_sq.label("purchase_count"),
            is_active_expr,
            is_expired_expr,
        )
        .where(*base_filters)
        .where(active_filter)
        .order_by(TimeSale.created_at.desc())
    )

    row = db.execute(stmt).first()
    if not row:
        return None

    ts, purchase_count, is_active, is_expired = row
    if not is_active:
        return None

    return {
        "id": ts.id,
        "sale_percentage": ts.sale_percentage,
        "start_date": ts.start_date,
        "end_date": ts.end_date,
        "max_purchase_count": ts.max_purchase_count,
        "purchase_count": int(purchase_count) if purchase_count is not None else 0,
        "is_active": bool(is_active),
        "is_expired": bool(is_expired),
    }


def get_plan_time_sale_by_id(db: Session, time_sale_id: UUID):
    """プランのタイムセール情報をIDから取得（ステータス付き）"""
    now = func.now()
    within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)

    start_bound = TimeSale.start_date
    end_bound = TimeSale.end_date

    purchase_count_sq = (
        select(func.count(Payments.id))
        .where(
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.paid_at.is_not(None),
            Payments.paid_at >= start_bound,
            Payments.paid_at <= end_bound,
            Payments.order_id == cast(TimeSale.plan_id, String),
            Payments.payment_price == TimeSale.sale_price,
        )
        .correlate(TimeSale)
        .scalar_subquery()
    )

    is_active_expr = case(
        (TimeSale.max_purchase_count.is_(None), within_time),
        else_=and_(within_time, purchase_count_sq < TimeSale.max_purchase_count),
    ).label("is_active")

    is_expired_expr = case(
        (now >= TimeSale.end_date, True),
        (
            and_(
                TimeSale.max_purchase_count.is_not(None),
                within_time,
                purchase_count_sq >= TimeSale.max_purchase_count,
            ),
            True,
        ),
        else_=False,
    ).label("is_expired")

    stmt = select(
        TimeSale,
        purchase_count_sq.label("purchase_count"),
        is_active_expr,
        is_expired_expr,
    ).where(
        TimeSale.id == time_sale_id,
        TimeSale.plan_id.is_not(None),
        TimeSale.price_id.is_(None),
        TimeSale.post_id.is_(None),
        TimeSale.deleted_at.is_(None),
    )

    row = db.execute(stmt).first()
    return row


def get_price_time_sale_by_id(db: Session, time_sale_id: UUID):
    """投稿の価格タイムセール情報をIDから取得（ステータス付き）"""
    now = func.now()
    within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)

    start_bound = TimeSale.start_date
    end_bound = TimeSale.end_date

    purchase_count_sq = (
        select(func.count(Payments.id))
        .where(
            Payments.status == PaymentStatus.SUCCEEDED,
            Payments.paid_at.is_not(None),
            Payments.paid_at >= start_bound,
            Payments.paid_at <= end_bound,
            Payments.order_id == cast(TimeSale.price_id, String),
            Payments.payment_price == TimeSale.sale_price,
        )
        .correlate(TimeSale)
        .scalar_subquery()
    )

    is_active_expr = case(
        (TimeSale.max_purchase_count.is_(None), within_time),
        else_=and_(within_time, purchase_count_sq < TimeSale.max_purchase_count),
    ).label("is_active")

    is_expired_expr = case(
        (now >= TimeSale.end_date, True),
        (
            and_(
                TimeSale.max_purchase_count.is_not(None),
                within_time,
                purchase_count_sq >= TimeSale.max_purchase_count,
            ),
            True,
        ),
        else_=False,
    ).label("is_expired")

    stmt = select(
        TimeSale,
        purchase_count_sq.label("purchase_count"),
        is_active_expr,
        is_expired_expr,
    ).where(
        TimeSale.id == time_sale_id,
        TimeSale.post_id.is_not(None),
        TimeSale.price_id.is_not(None),
        TimeSale.plan_id.is_(None),
        TimeSale.deleted_at.is_(None),
    )

    row = db.execute(stmt).first()
    return row


def get_post_sale_flag_map(db: Session, post_ids: List[UUID]) -> Dict[UUID, bool]:
    if not post_ids:
        return {}

    now = func.now()
    out: Dict[UUID, bool] = {pid: False for pid in post_ids}

    # -------------------------
    # A) PRICE SALE (post_id + active price_id)
    # -------------------------
    price_rows = db.execute(
        select(Prices.post_id, Prices.id.label("price_id")).where(
            Prices.post_id.in_(post_ids),
            Prices.is_active.is_(True),
            Prices.price > 0,
        )
    ).all()

    post_to_price_id = {r.post_id: r.price_id for r in price_rows}
    price_ids = list(post_to_price_id.values())

    if price_ids:
        purchase_count_sq = (
            select(func.count(Payments.id))
            .where(
                Payments.status == PaymentStatus.SUCCEEDED,
                Payments.paid_at.is_not(None),
                Payments.paid_at >= TimeSale.start_date,
                Payments.paid_at <= TimeSale.end_date,
                Payments.order_id == cast(TimeSale.price_id, String),
                Payments.payment_price == TimeSale.sale_price,
            )
            .correlate(TimeSale)
            .scalar_subquery()
        )

        within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)
        price_sale_active_cond = and_(
            TimeSale.deleted_at.is_(None),
            TimeSale.post_id.is_not(None),
            TimeSale.price_id.in_(price_ids),
            TimeSale.plan_id.is_(None),
            TimeSale.start_date.is_not(None),
            TimeSale.end_date.is_not(None),
            within_time,
            or_(
                TimeSale.max_purchase_count.is_(None),
                purchase_count_sq < TimeSale.max_purchase_count,
            ),
        )

        active_price_ids = set(
            db.execute(select(TimeSale.price_id).where(price_sale_active_cond))
            .scalars()
            .all()
        )

        for pid, price_id in post_to_price_id.items():
            if price_id in active_price_ids:
                out[pid] = True

    # -------------------------
    # B) PLAN SALE (post_plans -> plans -> time_sale)
    # -------------------------
    pp_rows = db.execute(
        select(PostPlans.post_id, PostPlans.plan_id).where(
            PostPlans.post_id.in_(post_ids)
        )
    ).all()

    post_to_plan_ids: Dict[UUID, List[UUID]] = {}
    for r in pp_rows:
        post_to_plan_ids.setdefault(r.post_id, []).append(r.plan_id)

    all_plan_ids = list({r.plan_id for r in pp_rows})
    if all_plan_ids:
        paid_plan_ids = set(
            db.execute(
                select(Plans.id).where(
                    Plans.id.in_(all_plan_ids),
                    Plans.price > 0,
                    Plans.deleted_at.is_(None),
                )
            )
            .scalars()
            .all()
        )

        if paid_plan_ids:
            purchase_count_sq_plan = (
                select(func.count(Payments.id))
                .where(
                    Payments.status == PaymentStatus.SUCCEEDED,
                    Payments.paid_at.is_not(None),
                    Payments.paid_at >= TimeSale.start_date,
                    Payments.paid_at <= TimeSale.end_date,
                    Payments.order_id == cast(TimeSale.plan_id, String),
                    Payments.payment_price == TimeSale.sale_price,
                )
                .correlate(TimeSale)
                .scalar_subquery()
            )

            within_time_plan = and_(TimeSale.start_date <= now, now < TimeSale.end_date)
            plan_sale_active_cond = and_(
                TimeSale.deleted_at.is_(None),
                TimeSale.plan_id.in_(paid_plan_ids),
                TimeSale.price_id.is_(None),
                TimeSale.post_id.is_(None),
                TimeSale.start_date.is_not(None),
                TimeSale.end_date.is_not(None),
                within_time_plan,
                or_(
                    TimeSale.max_purchase_count.is_(None),
                    purchase_count_sq_plan < TimeSale.max_purchase_count,
                ),
            )

            active_plan_ids = set(
                db.execute(select(TimeSale.plan_id).where(plan_sale_active_cond))
                .scalars()
                .all()
            )

            for pid, plan_ids in post_to_plan_ids.items():
                if out[pid]:
                    continue
                if any(
                    (plid in active_plan_ids)
                    for plid in plan_ids
                    if plid in paid_plan_ids
                ):
                    out[pid] = True

    return out


def get_post_time_sale_details_map(
    db: Session, post_ids: List[UUID]
) -> Dict[UUID, Dict]:
    """
    投稿の単品時間セール詳細情報をマップで取得

    Returns:
        Dict[UUID, Dict]: 投稿IDをキーに、{'sale_percentage': int}を値とする辞書
    """
    if not post_ids:
        return {}

    now = func.now()
    out: Dict[UUID, Dict] = {}

    # -------------------------
    # A) PRICE SALE (post_id + active price_id) のみを取得
    # -------------------------
    price_rows = db.execute(
        select(Prices.post_id, Prices.id.label("price_id")).where(
            Prices.post_id.in_(post_ids),
            Prices.is_active.is_(True),
            Prices.price > 0,
        )
    ).all()

    post_to_price_id = {r.post_id: r.price_id for r in price_rows}
    price_ids = list(post_to_price_id.values())

    if price_ids:
        purchase_count_sq = (
            select(func.count(Payments.id))
            .where(
                Payments.status == PaymentStatus.SUCCEEDED,
                Payments.paid_at.is_not(None),
                Payments.paid_at >= TimeSale.start_date,
                Payments.paid_at <= TimeSale.end_date,
                Payments.order_id == cast(TimeSale.price_id, String),
                Payments.payment_price == TimeSale.sale_price,
            )
            .correlate(TimeSale)
            .scalar_subquery()
        )

        within_time = and_(TimeSale.start_date <= now, now < TimeSale.end_date)
        price_sale_active_cond = and_(
            TimeSale.deleted_at.is_(None),
            TimeSale.post_id.is_not(None),
            TimeSale.price_id.in_(price_ids),
            TimeSale.plan_id.is_(None),
            TimeSale.start_date.is_not(None),
            TimeSale.end_date.is_not(None),
            within_time,
            or_(
                TimeSale.max_purchase_count.is_(None),
                purchase_count_sq < TimeSale.max_purchase_count,
            ),
        )

        active_sales = db.execute(
            select(TimeSale.post_id, TimeSale.sale_percentage).where(
                price_sale_active_cond
            )
        ).all()

        for post_id, sale_percentage in active_sales:
            if post_id not in out:
                out[post_id] = {"sale_percentage": sale_percentage}

    return out


def delete_plan_time_sale_by_id(db: Session, time_sale_id: UUID, current_user_id: UUID):
    """プランの価格時間販売情報を削除する"""
    time_sale = db.query(TimeSale).filter(TimeSale.id == time_sale_id).first()
    if not time_sale:
        return False
    try:
        db.delete(time_sale)
        db.commit()
        return True
    except Exception as e:
        logger.exception(f"Delete plan time sale error: {e}")
        db.rollback()
        return False


def delete_price_time_sale_by_id(
    db: Session, time_sale_id: UUID, current_user_id: UUID
):
    """価格の価格時間販売情報を削除する"""
    time_sale = db.query(TimeSale).filter(TimeSale.id == time_sale_id).first()
    if not time_sale:
        return False
    try:
        db.delete(time_sale)
        db.commit()
        return True
    except Exception as e:
        logger.exception(f"Delete price time sale error: {e}")
        db.rollback()
        return False


def update_price_time_sale_by_id(
    db: Session, time_sale_id: UUID, payload: UpdateRequest, current_user_id: UUID
):
    """価格の価格時間販売情報を更新する"""
    time_sale = db.query(TimeSale).filter(TimeSale.id == time_sale_id).first()
    if not time_sale:
        return False
    price = None
    if time_sale.price_id is None:
        if check_exists_plan_time_sale_in_period_by_plan_id(
            db, time_sale.plan_id, payload.start_date, payload.end_date, time_sale_id
        ):
            raise HTTPException(
                status_code=400, detail="Plan time sale is already exists in period"
            )
        plan = db.query(Plans).filter(Plans.id == time_sale.plan_id).first()
        if not plan:
            return False
        price = plan.price
    if time_sale.plan_id is None:
        if check_exists_price_time_sale_in_period_by_post_id(
            db,
            time_sale.post_id,
            # time_sale.price_id,
            payload.start_date,
            payload.end_date,
            time_sale_id,
        ):
            raise HTTPException(
                status_code=400, detail="Price time sale is already exists in period"
            )
        price = db.query(Prices).filter(Prices.id == time_sale.price_id).first()
        if not price:
            return False
        price = price.price

    try:
        new_sale_price = price - math.ceil(price * payload.sale_percentage / 100)
        time_sale.start_date = payload.start_date
        time_sale.end_date = payload.end_date
        time_sale.sale_percentage = payload.sale_percentage
        time_sale.max_purchase_count = payload.max_purchase_count
        time_sale.sale_price = new_sale_price
        time_sale.updated_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as e:
        logger.exception(f"Update price time sale error: {e}")
        db.rollback()
        return False
