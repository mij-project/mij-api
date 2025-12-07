from ast import Sub
from datetime import datetime, timedelta, timezone
from sqlalchemy import and_, or_, select, func
from sqlalchemy.orm import Session, aliased
from app.models import Payments, Profiles
from app.models.subscriptions import Subscriptions
from app.core.logger import Logger
from app.constants.enums import SubscriptionStatus

logger = Logger.get_logger()


def get_subscriptions_summary(db: Session):
    try:
        now = datetime.now(timezone.utc)
        start_of_this_month = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(hours=9)
        end_of_this_month = now.replace(
            hour=23, minute=59, second=59, microsecond=999999
        ) - timedelta(hours=9)

        # Total subscriptions active
        total_subscriptions_active = (
            db.query(Subscriptions)
            .filter(
                or_(
                    and_(
                        Subscriptions.access_type == 1,
                        Subscriptions.status == SubscriptionStatus.ACTIVE,
                    ),
                    and_(
                        Subscriptions.status == 2,
                        Subscriptions.last_payment_failed_at.is_(None),
                    ),
                )
            )
            .count()
        )

        # New subscriptions this month
        first_subq = (
            select(
                Subscriptions.user_id.label("user_id"),
                Subscriptions.order_id.label("order_id"),
                func.min(Subscriptions.access_start).label("first_access_start"),
                func.count().label("cnt"),
            )
            .where(
                Subscriptions.access_type == 1,
                Subscriptions.status == SubscriptionStatus.ACTIVE,
            )
            .group_by(Subscriptions.user_id, Subscriptions.order_id)
            .subquery()
        )
        first_subscriptions_this_month_stmt = select(func.count()).where(
            first_subq.c.first_access_start >= start_of_this_month,
            first_subq.c.first_access_start <= end_of_this_month,
            first_subq.c.cnt == 1,
        )
        new_subscriptions_this_month_count = (
            db.execute(first_subscriptions_this_month_stmt).scalar() or 0
        )

        # Total subscriptions failed
        total_subscriptions_failed_count_stmt = select(
            func.count(Subscriptions.id)
        ).where(
            Subscriptions.access_type == 1,
            Subscriptions.last_payment_failed_at.isnot(None),
        )
        total_subscriptions_failed_count = (
            db.execute(total_subscriptions_failed_count_stmt).scalar() or 0
        )

        return {
            "total_subscriptions_active": total_subscriptions_active,
            "new_subscriptions_this_month_count": new_subscriptions_this_month_count,
            "total_subscriptions_failed_count": total_subscriptions_failed_count,
        }

    except Exception as e:
        logger.error(f"Get subscriptions summary error: {e}")
        return None


def get_subscriptions_info(
    db: Session,
    start_date: datetime,
    end_date: datetime,
    filter: int,
    page: int,
    limit: int,
):
    try:
        if filter == 0:
            subscriptions, total = __get_subscriptions_info_all(
                db, start_date, end_date, page, limit
            )
        elif filter == 1:
            subscriptions, total = __get_subscriptions_info_active(
                db, start_date, end_date, page, limit
            )
        elif filter == 2:
            subscriptions, total = __get_subscriptions_info_failed(
                db, start_date, end_date, page, limit
            )
        # elif filter == 3:
        #     subscriptions, total = __get_subscriptions_info_canceled(
        #         db, start_date, end_date, page, limit
        #     )

        return {
            "subscriptions": subscriptions,
            "total_items": total,
        }
    except Exception as e:
        logger.error(f"Get subscriptions info error: {e}")
        return None


def __get_subscriptions_info_all(
    db: Session, start_date: datetime, end_date: datetime, page: int, limit: int
):
    offset = (page - 1) * limit

    start_naive = start_date.replace(tzinfo=None)
    end_naive = end_date.replace(tzinfo=None)

    SubscriberProfile = aliased(Profiles)
    CreatorProfile = aliased(Profiles)

    base_q = (
        db.query(
            Subscriptions,
            SubscriberProfile.username.label("subscriber_username"),
            CreatorProfile.username.label("creator_username"),
            Payments.id.label("payment_id"),
            Payments.payment_price.label("money"),
        )
        .join(SubscriberProfile, Subscriptions.user_id == SubscriberProfile.user_id)
        .join(CreatorProfile, Subscriptions.creator_id == CreatorProfile.user_id)
        .outerjoin(Payments, Subscriptions.payment_id == Payments.id)
        .filter(
            Subscriptions.access_type == 1,
            Subscriptions.access_start >= start_naive,
            Subscriptions.access_start <= end_naive,
        )
    )

    total = (
        base_q.with_entities(func.count(func.distinct(Subscriptions.id))).scalar() or 0
    )

    rows = (
        base_q.order_by(Subscriptions.access_start.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return rows, total


def __get_subscriptions_info_active(
    db: Session, start_date: datetime, end_date: datetime, page: int, limit: int
):
    offset = (page - 1) * limit
    start_naive = start_date.replace(tzinfo=None)
    end_naive = end_date.replace(tzinfo=None)

    SubscriberProfile = aliased(Profiles)
    CreatorProfile = aliased(Profiles)

    base_q = (
        db.query(
            Subscriptions,
            SubscriberProfile.username.label("subscriber_username"),
            CreatorProfile.username.label("creator_username"),
            Payments.id.label("payment_id"),
            Payments.payment_price.label("money"),
        )
        .join(SubscriberProfile, Subscriptions.user_id == SubscriberProfile.user_id)
        .join(CreatorProfile, Subscriptions.creator_id == CreatorProfile.user_id)
        .outerjoin(Payments, Subscriptions.payment_id == Payments.id)
        .filter(
            and_(
                or_(
                    and_(
                        Subscriptions.access_type == 1,
                        Subscriptions.status == SubscriptionStatus.ACTIVE,
                    ),
                    and_(
                        Subscriptions.access_type == 1,
                        Subscriptions.status == 2,
                        Subscriptions.last_payment_failed_at.is_(None),
                    ),
                ),
                Subscriptions.access_start >= start_naive,
                Subscriptions.access_start <= end_naive,
            ),
        )
    )

    total = (
        base_q.with_entities(func.count(func.distinct(Subscriptions.id))).scalar() or 0
    )

    rows = (
        base_q.order_by(Subscriptions.access_start.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return rows, total


def __get_subscriptions_info_failed(
    db: Session, start_date: datetime, end_date: datetime, page: int, limit: int
):
    offset = (page - 1) * limit
    start_naive = start_date.replace(tzinfo=None)
    end_naive = end_date.replace(tzinfo=None)

    SubscriberProfile = aliased(Profiles)
    CreatorProfile = aliased(Profiles)

    base_q = (
        db.query(
            Subscriptions,
            SubscriberProfile.username.label("subscriber_username"),
            CreatorProfile.username.label("creator_username"),
            Payments.id.label("payment_id"),
            Payments.payment_price.label("money"),
        )
        .join(SubscriberProfile, Subscriptions.user_id == SubscriberProfile.user_id)
        .join(CreatorProfile, Subscriptions.creator_id == CreatorProfile.user_id)
        .outerjoin(Payments, Subscriptions.payment_id == Payments.id)
        .filter(
            and_(
                Subscriptions.access_type == 1,
                Subscriptions.status == 3,
                Subscriptions.last_payment_failed_at.isnot(None),
                Subscriptions.access_start >= start_naive,
                Subscriptions.access_start <= end_naive,
            )
        )
    )

    total = (
        base_q.with_entities(func.count(func.distinct(Subscriptions.id))).scalar() or 0
    )

    rows = (
        base_q.order_by(Subscriptions.access_start.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return rows, total
