from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import distinct, literal, or_, select, func, and_, desc, cast
from sqlalchemy.sql import and_ as sa_and, or_ as sa_or
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from uuid import UUID
from datetime import datetime, timedelta, timezone
from app.models import Bookmarks, Categories, Payments, PostCategories, Prices
from app.models.creators import Creators
from app.models.plans import PostPlans
from app.models.posts import Posts
from app.models.user import Users
from app.models.identity import IdentityVerifications, IdentityDocuments
from app.schemas.creator import (
    CreatorUpdate,
    IdentityVerificationCreate,
    IdentityDocumentCreate,
)
from app.constants.enums import (
    CreatorStatus,
    PostStatus,
    VerificationStatus,
    AccountType,
    PaymentStatus,
    PaymentType,
)
from app.models.profiles import Profiles
from app.models.social import Follows, Likes


def create_creator(db: Session, creator_create: dict) -> Creators:
    db_creator = Creators(**creator_create)
    db.add(db_creator)
    db.commit()
    db.refresh(db_creator)
    return db_creator


def update_creator_status(
    db: Session, user_id: UUID, status: CreatorStatus
) -> Creators:
    """
    クリエイターステータスを更新する
    """
    creator = db.scalar(select(Creators).where(Creators.user_id == user_id))
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    creator.status = status
    return creator


def update_creator(
    db: Session, user_id: UUID, creator_update: CreatorUpdate
) -> Creators:
    """
    クリエイター情報を更新する

    Args:
        db: データベースセッション
        user_id: ユーザーID
        creator_update: クリエイター更新情報
    """
    creator = db.scalar(select(Creators).where(Creators.user_id == user_id))
    if not creator:
        raise HTTPException(status_code=404, detail="Creator not found")

    update_data = creator_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(creator, field, value)

    db.commit()
    db.refresh(creator)
    return creator


def get_creator_by_user_id(db: Session, user_id: UUID) -> Creators:
    """
    ユーザーIDによるクリエイター取得

    Args:
        db: データベースセッション
        user_id: ユーザーID
    """
    return db.scalar(select(Creators).where(Creators.user_id == user_id))


def create_identity_verification(
    db: Session, verification_create: IdentityVerificationCreate
) -> IdentityVerifications:
    """
    本人確認レコードを作成する

    Args:
        db: データベースセッション
        verification_create: 本人確認作成情報
    """
    existing_verification = db.scalar(
        select(IdentityVerifications).where(
            IdentityVerifications.user_id == verification_create.user_id
        )
    )

    if existing_verification:
        return existing_verification

    db_verification = IdentityVerifications(
        user_id=verification_create.user_id, status=VerificationStatus.PENDING
    )
    db.add(db_verification)
    db.commit()
    db.refresh(db_verification)
    return db_verification


def update_identity_verification_status(
    db: Session, user_id: UUID, status: int, notes: str = None
) -> IdentityVerifications:
    """
    本人確認ステータスを更新する

    Args:
        db: データベースセッション
        user_id: ユーザーID
        status: ステータス
        notes: 備考
    """
    verification = db.scalar(
        select(IdentityVerifications).where(IdentityVerifications.user_id == user_id)
    )

    if not verification:
        raise HTTPException(status_code=404, detail="Identity verification not found")

    verification.status = status
    verification.notes = notes
    if status == VerificationStatus.APPROVED:
        verification.checked_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(verification)
    return verification


def create_identity_document(
    db: Session, document_create: IdentityDocumentCreate
) -> IdentityDocuments:
    """
    本人確認書類を作成する

    Args:
        db: データベースセッション
        document_create: 書類作成情報
    """
    db_document = IdentityDocuments(
        verification_id=document_create.verification_id,
        kind=document_create.kind,
        storage_key=document_create.storage_key,
    )
    db.add(db_document)
    db.commit()
    db.refresh(db_document)
    return db_document


def get_identity_verification_by_user_id(
    db: Session, user_id: UUID
) -> IdentityVerifications:
    """
    ユーザーIDによる本人確認情報取得

    Args:
        db: データベースセッション
        user_id: ユーザーID
    """
    return db.scalar(
        select(IdentityVerifications).where(IdentityVerifications.user_id == user_id)
    )


def get_creators(db: Session, limit: int = 50):
    from sqlalchemy import func
    from app.models.social import Follows

    return (
        db.query(
            Users,
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.coalesce(func.count(distinct(Follows.follower_user_id)), 0).label(
                "followers_count"
            ),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Follows.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
        .group_by(Users.id, Users.profile_name, Profiles.username, Profiles.avatar_url)
        .order_by(desc(Users.created_at))
        .limit(limit)
        .all()
    )


def get_top_creators(db: Session, limit: int = 5, current_user=None):
    """
    フォロワー数上位のクリエイターを取得
    """
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    likes_agg = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Posts)
        .join(Likes, Likes.post_id == Posts.id)
        .filter(active_post_cond)
        .group_by(Posts.creator_user_id)
        .subquery("likes_agg")
    )

    followers_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_agg")
    )
    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.coalesce(followers_agg.c.followers_count, 0).label("followers_count"),
            func.coalesce(likes_agg.c.likes_count, 0).label("likes_count"),
            is_following_col,
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(likes_agg, likes_agg.c.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
    )
    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )
    return q.order_by(desc("likes_count")).limit(limit).all()


def get_new_creators(db: Session, limit: int = 5):
    """
    登録順最新のクリエイターを取得
    """
    return (
        db.query(
            Users,
            Users.offical_flg,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(Users.role == AccountType.CREATOR)
        .order_by(desc(Users.created_at))
        .limit(limit)
        .all()
    )


def get_ranking_creators_overall_all_time(
    db: Session, limit: int = 500, current_user=None
):
    """
    いいね数が多いCreator overalltime
    """
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    likes_agg = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Posts)
        .join(Likes, Likes.post_id == Posts.id)
        .filter(active_post_cond)
        .group_by(Posts.creator_user_id)
        .subquery("likes_agg")
    )

    followers_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_agg")
    )
    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.coalesce(followers_agg.c.followers_count, 0).label("followers_count"),
            func.coalesce(likes_agg.c.likes_count, 0).label("likes_count"),
            is_following_col,
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(likes_agg, likes_agg.c.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
    )
    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )
    return q.order_by(desc("likes_count")).limit(limit).all()


def get_ranking_creators_overall_daily(
    db: Session, limit: int = 500, current_user=None
):
    """
    いいね数が多いCreator daily
    """
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    now = func.now()

    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    # 1) likes_agg: creator -> likes_count (daily)
    likes_agg = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Posts)
        .join(Likes, and_(Likes.post_id == Posts.id, Likes.created_at >= one_day_ago))
        .filter(active_post_cond)
        .group_by(Posts.creator_user_id)
        .subquery("likes_agg")
    )

    # 2) followers_agg: creator -> followers_count (all time)
    followers_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_agg")
    )

    # 3) viewer_follow_map: creator -> True (only if current_user_id)
    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.coalesce(followers_agg.c.followers_count, 0).label("followers_count"),
            func.coalesce(likes_agg.c.likes_count, 0).label("likes_count"),
            is_following_col,
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(likes_agg, likes_agg.c.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(func.coalesce(likes_agg.c.likes_count, 0) > 0)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )

    return q.order_by(desc("likes_count")).limit(limit).all()


def get_ranking_creators_overall_weekly(
    db: Session, limit: int = 500, current_user=None
):
    """
    いいね数が多いCreator weekly
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    now = func.now()

    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    # 1) likes_agg: creator -> likes_count (weekly)
    likes_agg = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Posts)
        .join(Likes, and_(Likes.post_id == Posts.id, Likes.created_at >= one_week_ago))
        .filter(active_post_cond)
        .group_by(Posts.creator_user_id)
        .subquery("likes_agg")
    )

    # 2) followers_agg: creator -> followers_count (all time)
    followers_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_agg")
    )

    # 3) viewer_follow_map: creator -> True (only if current_user_id)
    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.coalesce(followers_agg.c.followers_count, 0).label("followers_count"),
            func.coalesce(likes_agg.c.likes_count, 0).label("likes_count"),
            is_following_col,
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(likes_agg, likes_agg.c.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(func.coalesce(likes_agg.c.likes_count, 0) > 0)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )

    return q.order_by(desc("likes_count")).limit(limit).all()


def get_ranking_creators_overall_monthly(
    db: Session, limit: int = 500, current_user=None
):
    """
    いいね数が多いCreator monthly
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

    now = func.now()

    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    # 1) likes_agg: creator -> likes_count (monthly)
    likes_agg = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Posts)
        .join(Likes, and_(Likes.post_id == Posts.id, Likes.created_at >= one_month_ago))
        .filter(active_post_cond)
        .group_by(Posts.creator_user_id)
        .subquery("likes_agg")
    )

    # 2) followers_agg: creator -> followers_count (all time)
    followers_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_agg")
    )

    # 3) viewer_follow_map: creator -> True (only if current_user_id)
    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.coalesce(followers_agg.c.followers_count, 0).label("followers_count"),
            func.coalesce(likes_agg.c.likes_count, 0).label("likes_count"),
            is_following_col,
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(likes_agg, likes_agg.c.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(func.coalesce(likes_agg.c.likes_count, 0) > 0)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )

    return q.order_by(desc("likes_count")).limit(limit).all()


def get_ranking_creators_overall_detail_overall(
    db: Session,
    page: int = 1,
    limit: int = 500,
    term: str = "all_time",
    current_user=None,
):
    """
    いいね数が多いCreator overalltime
    """
    if term == "all_time":
        filter_date_condition = None
    elif term == "monthly":
        filter_date_condition = Likes.created_at >= datetime.now(
            timezone.utc
        ) - timedelta(days=30)
    elif term == "weekly":
        filter_date_condition = Likes.created_at >= datetime.now(
            timezone.utc
        ) - timedelta(days=7)
    elif term == "daily":
        filter_date_condition = Likes.created_at >= datetime.now(
            timezone.utc
        ) - timedelta(days=1)

    offset = (page - 1) * limit

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    likes_join_cond = Likes.post_id == Posts.id
    if filter_date_condition is not None:
        likes_join_cond = and_(
            likes_join_cond, Likes.created_at >= filter_date_condition
        )
    likes_agg = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .select_from(Posts)
        .outerjoin(Likes, likes_join_cond)
        .filter(active_post_cond)
        .group_by(Posts.creator_user_id)
        .subquery("likes_agg")
    )
    followers_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_agg")
    )
    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")
    q = (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.coalesce(followers_agg.c.followers_count, 0).label("followers_count"),
            func.coalesce(likes_agg.c.likes_count, 0).label("likes_count"),
            is_following_col,
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(likes_agg, likes_agg.c.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )
    if filter_date_condition is not None:
        q = q.filter(func.coalesce(likes_agg.c.likes_count, 0) > 0)

    return q.order_by(desc("likes_count")).offset(offset).limit(limit).all()


def get_ranking_creators_categories_all_time(db: Session, limit: int = 500):
    """
    いいね数が多いCreator categories alltime
    """

    now = func.now()

    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    creator_like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Users.id.label("creator_user_id"),
            Users.profile_name.label("profile_name"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            Profiles.cover_url.label("cover_url"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
            func.array_agg(distinct(Follows.follower_user_id)).label("follower_ids"),
        )
        .select_from(Categories)
        .join(PostCategories, PostCategories.category_id == Categories.id)
        .join(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .join(Users, Users.id == Posts.creator_user_id)
        .join(Profiles, Profiles.user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .outerjoin(Follows, Follows.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
        .group_by(
            Categories.id,
            Categories.name,
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .subquery("creator_like_counts")
    )

    top_categories_subq = (
        db.query(
            creator_like_counts_subq.c.category_id,
            creator_like_counts_subq.c.category_name,
            func.sum(creator_like_counts_subq.c.likes_count).label(
                "category_total_likes"
            ),
        )
        .select_from(creator_like_counts_subq)
        .group_by(
            creator_like_counts_subq.c.category_id,
            creator_like_counts_subq.c.category_name,
        )
        .order_by(desc("category_total_likes"))
        .limit(10)
        .subquery("top_categories")
    )

    ranked_creators_subq = (
        db.query(
            creator_like_counts_subq.c.category_id,
            creator_like_counts_subq.c.category_name,
            creator_like_counts_subq.c.creator_user_id,
            creator_like_counts_subq.c.profile_name,
            creator_like_counts_subq.c.username,
            creator_like_counts_subq.c.avatar_url,
            creator_like_counts_subq.c.cover_url,
            creator_like_counts_subq.c.likes_count,
            creator_like_counts_subq.c.followers_count,
            creator_like_counts_subq.c.follower_ids,
            func.row_number()
            .over(
                partition_by=creator_like_counts_subq.c.category_id,
                order_by=creator_like_counts_subq.c.likes_count.desc(),
            )
            .label("rn"),
        )
        .select_from(creator_like_counts_subq)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == creator_like_counts_subq.c.category_id,
        )
        .subquery("ranked_creators")
    )

    result = (
        db.query(ranked_creators_subq)
        .filter(ranked_creators_subq.c.rn <= limit)
        .order_by(
            ranked_creators_subq.c.category_name,
            ranked_creators_subq.c.likes_count.desc(),
        )
        .all()
    )

    return result


def get_ranking_creators_categories_overall_all_time(
    db: Session, limit: int = 500, current_user=None
):
    """
    いいね数が多いCreator categories overall alltime
    """

    now = func.now()

    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    likes_agg = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Posts.creator_user_id.label("creator_user_id"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .select_from(Categories)
        .join(PostCategories, PostCategories.category_id == Categories.id)
        .join(Posts, and_(Posts.id == PostCategories.post_id, active_post_cond))
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .group_by(Categories.id, Categories.name, Posts.creator_user_id)
        .subquery("likes_agg")
    )

    top_categories_subq = (
        db.query(
            likes_agg.c.category_id,
            likes_agg.c.category_name,
            func.sum(likes_agg.c.likes_count).label("category_total_likes"),
        )
        .select_from(likes_agg)
        .group_by(likes_agg.c.category_id, likes_agg.c.category_name)
        .order_by(desc("category_total_likes"))
        .limit(10)
        .subquery("top_categories")
    )

    followers_count_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_count_agg")
    )

    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            likes_agg.c.category_id,
            likes_agg.c.category_name,
            likes_agg.c.creator_user_id,
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            Profiles.cover_url.label("cover_url"),
            likes_agg.c.likes_count.label("likes_count"),
            func.coalesce(followers_count_agg.c.followers_count, 0).label(
                "followers_count"
            ),
            is_following_col,
            func.row_number()
            .over(
                partition_by=likes_agg.c.category_id,
                order_by=likes_agg.c.likes_count.desc(),
            )
            .label("rn"),
        )
        .select_from(likes_agg)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == likes_agg.c.category_id,
        )
        .join(Users, Users.id == likes_agg.c.creator_user_id)
        .join(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            followers_count_agg,
            followers_count_agg.c.creator_user_id == likes_agg.c.creator_user_id,
        )
        .filter(Users.role == AccountType.CREATOR)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map,
            viewer_follow_map.c.creator_user_id == likes_agg.c.creator_user_id,
        )

    ranked_creators_subq = q.subquery("ranked_creators")

    result = (
        db.query(ranked_creators_subq)
        .filter(ranked_creators_subq.c.rn <= limit)
        .order_by(
            ranked_creators_subq.c.category_name,
            ranked_creators_subq.c.likes_count.desc(),
        )
        .all()
    )

    return result


def get_ranking_creators_categories_overall_daily(
    db: Session, limit: int = 500, current_user=None
):
    """
    いいね数が多いCreator categories overall daily
    """
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    now = func.now()

    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    likes_agg = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Posts.creator_user_id.label("creator_user_id"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .select_from(Categories)
        .join(PostCategories, PostCategories.category_id == Categories.id)
        .join(Posts, and_(Posts.id == PostCategories.post_id, active_post_cond))
        .outerjoin(
            Likes, and_(Likes.post_id == Posts.id, Likes.created_at >= one_day_ago)
        )
        .group_by(Categories.id, Categories.name, Posts.creator_user_id)
        .subquery("likes_agg")
    )

    top_categories_subq = (
        db.query(
            likes_agg.c.category_id,
            likes_agg.c.category_name,
            func.sum(likes_agg.c.likes_count).label("category_total_likes"),
        )
        .select_from(likes_agg)
        .group_by(likes_agg.c.category_id, likes_agg.c.category_name)
        .order_by(desc("category_total_likes"))
        .limit(10)
        .subquery("top_categories")
    )

    followers_count_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_count_agg")
    )

    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            likes_agg.c.category_id,
            likes_agg.c.category_name,
            likes_agg.c.creator_user_id,
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            Profiles.cover_url.label("cover_url"),
            likes_agg.c.likes_count.label("likes_count"),
            func.coalesce(followers_count_agg.c.followers_count, 0).label(
                "followers_count"
            ),
            is_following_col,
            func.row_number()
            .over(
                partition_by=likes_agg.c.category_id,
                order_by=likes_agg.c.likes_count.desc(),
            )
            .label("rn"),
        )
        .select_from(likes_agg)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == likes_agg.c.category_id,
        )
        .join(Users, Users.id == likes_agg.c.creator_user_id)
        .join(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            followers_count_agg,
            followers_count_agg.c.creator_user_id == likes_agg.c.creator_user_id,
        )
        .filter(Users.role == AccountType.CREATOR)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map,
            viewer_follow_map.c.creator_user_id == likes_agg.c.creator_user_id,
        )

    ranked_creators_subq = q.subquery("ranked_creators")

    result = (
        db.query(ranked_creators_subq)
        .filter(ranked_creators_subq.c.rn <= limit)
        .order_by(
            ranked_creators_subq.c.category_name,
            ranked_creators_subq.c.likes_count.desc(),
        )
        .all()
    )

    return result


def get_ranking_creators_categories_overall_weekly(
    db: Session, limit: int = 500, current_user=None
):
    """
    いいね数が多いCreator categories overall weekly
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    likes_agg = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Posts.creator_user_id.label("creator_user_id"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .select_from(Categories)
        .join(PostCategories, PostCategories.category_id == Categories.id)
        .join(Posts, and_(Posts.id == PostCategories.post_id, active_post_cond))
        .outerjoin(
            Likes, and_(Likes.post_id == Posts.id, Likes.created_at >= one_week_ago)
        )
        .group_by(Categories.id, Categories.name, Posts.creator_user_id)
        .subquery("likes_agg")
    )

    top_categories_subq = (
        db.query(
            likes_agg.c.category_id,
            likes_agg.c.category_name,
            func.sum(likes_agg.c.likes_count).label("category_total_likes"),
        )
        .select_from(likes_agg)
        .group_by(likes_agg.c.category_id, likes_agg.c.category_name)
        .order_by(desc("category_total_likes"))
        .limit(10)
        .subquery("top_categories")
    )

    followers_count_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_count_agg")
    )

    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            likes_agg.c.category_id,
            likes_agg.c.category_name,
            likes_agg.c.creator_user_id,
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            Profiles.cover_url.label("cover_url"),
            likes_agg.c.likes_count.label("likes_count"),
            func.coalesce(followers_count_agg.c.followers_count, 0).label(
                "followers_count"
            ),
            is_following_col,
            func.row_number()
            .over(
                partition_by=likes_agg.c.category_id,
                order_by=likes_agg.c.likes_count.desc(),
            )
            .label("rn"),
        )
        .select_from(likes_agg)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == likes_agg.c.category_id,
        )
        .join(Users, Users.id == likes_agg.c.creator_user_id)
        .join(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            followers_count_agg,
            followers_count_agg.c.creator_user_id == likes_agg.c.creator_user_id,
        )
        .filter(Users.role == AccountType.CREATOR)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map,
            viewer_follow_map.c.creator_user_id == likes_agg.c.creator_user_id,
        )

    ranked_creators_subq = q.subquery("ranked_creators")

    result = (
        db.query(ranked_creators_subq)
        .filter(ranked_creators_subq.c.rn <= limit)
        .order_by(
            ranked_creators_subq.c.category_name,
            ranked_creators_subq.c.likes_count.desc(),
        )
        .all()
    )

    return result


def get_ranking_creators_categories_overall_monthly(
    db: Session, limit: int = 500, current_user=None
):
    """
    いいね数が多いCreator categories overall monthly
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    likes_agg = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Posts.creator_user_id.label("creator_user_id"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .select_from(Categories)
        .join(PostCategories, PostCategories.category_id == Categories.id)
        .join(Posts, and_(Posts.id == PostCategories.post_id, active_post_cond))
        .outerjoin(
            Likes, and_(Likes.post_id == Posts.id, Likes.created_at >= one_month_ago)
        )
        .group_by(Categories.id, Categories.name, Posts.creator_user_id)
        .subquery("likes_agg")
    )

    top_categories_subq = (
        db.query(
            likes_agg.c.category_id,
            likes_agg.c.category_name,
            func.sum(likes_agg.c.likes_count).label("category_total_likes"),
        )
        .select_from(likes_agg)
        .group_by(likes_agg.c.category_id, likes_agg.c.category_name)
        .order_by(desc("category_total_likes"))
        .limit(10)
        .subquery("top_categories")
    )

    followers_count_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_count_agg")
    )

    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    q = (
        db.query(
            likes_agg.c.category_id,
            likes_agg.c.category_name,
            likes_agg.c.creator_user_id,
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            Profiles.cover_url.label("cover_url"),
            likes_agg.c.likes_count.label("likes_count"),
            func.coalesce(followers_count_agg.c.followers_count, 0).label(
                "followers_count"
            ),
            is_following_col,
            func.row_number()
            .over(
                partition_by=likes_agg.c.category_id,
                order_by=likes_agg.c.likes_count.desc(),
            )
            .label("rn"),
        )
        .select_from(likes_agg)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == likes_agg.c.category_id,
        )
        .join(Users, Users.id == likes_agg.c.creator_user_id)
        .join(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            followers_count_agg,
            followers_count_agg.c.creator_user_id == likes_agg.c.creator_user_id,
        )
        .filter(Users.role == AccountType.CREATOR)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map,
            viewer_follow_map.c.creator_user_id == likes_agg.c.creator_user_id,
        )

    ranked_creators_subq = q.subquery("ranked_creators")

    result = (
        db.query(ranked_creators_subq)
        .filter(ranked_creators_subq.c.rn <= limit)
        .order_by(
            ranked_creators_subq.c.category_name,
            ranked_creators_subq.c.likes_count.desc(),
        )
        .all()
    )

    return result


def get_ranking_creators_categories_detail(
    db: Session,
    category: str,
    page: int = 1,
    limit: int = 500,
    term: str = "all_time",
    current_user=None,
    min_payment_price: int = 500,
):
    """
    Creator ranking in a category (detail list)
    Ranking:
      purchase_count DESC
      bookmark_count DESC
      followers_count DESC
      Users.id DESC

    Return shape compatible with old mapping:
      Users, Users.profile_name, Profiles.username, Profiles.avatar_url, Profiles.cover_url,
      followers_count, likes_count(=purchase_count), is_following
    """

    # ---------- period window
    now = datetime.now(timezone.utc)
    start_dt = None
    if term == "daily":
        start_dt = now - timedelta(days=1)
    elif term == "weekly":
        start_dt = now - timedelta(days=7)
    elif term == "monthly":
        start_dt = now - timedelta(days=30)
    # all_time => None

    offset = (page - 1) * limit
    if offset < 0:
        offset = 0

    # ---------- active post condition
    now_sql = func.now()
    active_post_cond = sa_and(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        sa_or(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now_sql),
        sa_or(Posts.expiration_at.is_(None), Posts.expiration_at > now_sql),
    )

    # ---------- constants
    PAYMENT_SUCCEEDED = PaymentStatus.SUCCEEDED
    ORDER_TYPE_PLAN = PaymentType.PLAN
    ORDER_TYPE_PRICE = PaymentType.SINGLE
    MIN_PAYMENT_PRICE = min_payment_price

    # =====================================================
    # A) purchase_count per creator in this category
    # =====================================================
    base_payment_cond = sa_and(
        Payments.status == PAYMENT_SUCCEEDED,
        Payments.payment_price >= MIN_PAYMENT_PRICE,
        Payments.paid_at.isnot(None),
    )
    if start_dt is not None:
        base_payment_cond = sa_and(base_payment_cond, Payments.paid_at >= start_dt)

    # price payments -> creator (category-scoped)
    price_purchase_creator_sq = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .select_from(Prices)
        .join(Posts, sa_and(Posts.id == Prices.post_id, active_post_cond))
        .join(
            PostCategories,
            sa_and(
                PostCategories.post_id == Posts.id,
                PostCategories.category_id == category,
            ),
        )
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PRICE,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == Prices.id,
                base_payment_cond,
            ),
        )
        .group_by(Posts.creator_user_id)
        .subquery("price_purchase_creator_sq")
    )

    # plan payments -> creator (category-scoped)
    plan_purchase_creator_sq = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .select_from(PostPlans)
        .join(Posts, sa_and(Posts.id == PostPlans.post_id, active_post_cond))
        .join(
            PostCategories,
            sa_and(
                PostCategories.post_id == Posts.id,
                PostCategories.category_id == category,
            ),
        )
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PLAN,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == PostPlans.plan_id,
                base_payment_cond,
            ),
        )
        .group_by(Posts.creator_user_id)
        .subquery("plan_purchase_creator_sq")
    )

    union_purchase_sq = (
        db.query(
            price_purchase_creator_sq.c.creator_user_id.label("creator_user_id"),
            price_purchase_creator_sq.c.purchase_count.label("purchase_count"),
        )
        .union_all(
            db.query(
                plan_purchase_creator_sq.c.creator_user_id.label("creator_user_id"),
                plan_purchase_creator_sq.c.purchase_count.label("purchase_count"),
            )
        )
        .subquery("union_purchase_sq")
    )

    purchase_creator_sq = (
        db.query(
            union_purchase_sq.c.creator_user_id.label("creator_user_id"),
            func.sum(union_purchase_sq.c.purchase_count).label("purchase_count"),
        )
        .group_by(union_purchase_sq.c.creator_user_id)
        .subquery("purchase_creator_sq")
    )

    # =====================================================
    # B) bookmark_count per creator in this category (period-scoped)
    # =====================================================
    bookmark_q = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Bookmarks.user_id)).label("bookmark_count"),
        )
        .select_from(Bookmarks)
        .join(Posts, sa_and(Posts.id == Bookmarks.post_id, active_post_cond))
        .join(
            PostCategories,
            sa_and(
                PostCategories.post_id == Posts.id,
                PostCategories.category_id == category,
            ),
        )
    )
    if start_dt is not None:
        bookmark_q = bookmark_q.filter(Bookmarks.created_at >= start_dt)

    bookmark_creator_sq = bookmark_q.group_by(Posts.creator_user_id).subquery(
        "bookmark_creator_sq"
    )

    # =====================================================
    # C) followers_count (all time)
    # =====================================================
    followers_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_agg")
    )

    # =====================================================
    # D) viewer follow map
    # =====================================================
    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    # =====================================================
    # E) restrict creators to those who actually have posts in this category
    # (prevents unrelated creators from appearing with all zeros)
    # =====================================================
    creators_in_category_sq = (
        db.query(Posts.creator_user_id.label("creator_user_id"))
        .select_from(Posts)
        .join(
            PostCategories,
            sa_and(
                PostCategories.post_id == Posts.id,
                PostCategories.category_id == category,
            ),
        )
        .filter(active_post_cond)
        .distinct()
        .subquery("creators_in_category_sq")
    )

    # ---------- main query (return old shape)
    q = (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.coalesce(followers_agg.c.followers_count, 0).label("followers_count"),
            # compatibility: keep likes_count key => purchase_count
            func.coalesce(purchase_creator_sq.c.purchase_count, 0).label("likes_count"),
            is_following_col,
        )
        .select_from(Users)
        .join(Profiles, Users.id == Profiles.user_id)
        .join(
            creators_in_category_sq,
            creators_in_category_sq.c.creator_user_id == Users.id,
        )
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(
            purchase_creator_sq, purchase_creator_sq.c.creator_user_id == Users.id
        )
        .outerjoin(
            bookmark_creator_sq, bookmark_creator_sq.c.creator_user_id == Users.id
        )
        .filter(Users.role == AccountType.CREATOR)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )

    # if start_dt is not None:
    #     q = q.filter(
    #         sa_or(
    #             func.coalesce(purchase_creator_sq.c.purchase_count, 0) > 0,
    #             func.coalesce(bookmark_creator_sq.c.bookmark_count, 0) > 0,
    #         )
    #     )

    return (
        q.order_by(
            func.coalesce(purchase_creator_sq.c.purchase_count, 0).desc(),
            func.coalesce(bookmark_creator_sq.c.bookmark_count, 0).desc(),
            func.coalesce(followers_agg.c.followers_count, 0).desc(),
            Users.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def update_creator_platform_fee_by_admin(
    db: Session, user_id: UUID, platform_fee_percent: int
) -> Creators:
    """
    クリエイターのプラットフォーム手数料を更新
    """
    creator = db.query(Creators).filter(Creators.user_id == user_id).first()
    if creator is None:
        raise ValueError("Creator not found")
    creator.platform_fee_percent = platform_fee_percent
    db.commit()
    db.refresh(creator)
    return creator


def get_ranking_creators_overall(
    db: Session,
    page: int = 1,
    limit: int = 20,
    period: str = "all_time",
    current_user=None,
    min_payment_price: int = 500,
):
    """
    Return rows shaped like old code:
      (Users, Users.profile_name, Profiles.username, Profiles.avatar_url, Profiles.cover_url,
       followers_count, likes_count, is_following)

    New ranking logic (creator):
      purchase_count DESC  (returned as likes_count for compatibility)
      bookmark_count DESC  (not returned, only used for ordering)
      followers_count DESC
      Users.id DESC
    """

    now_sql = func.now()
    now = datetime.now(timezone.utc)

    # -------- rolling window
    start_dt = None
    if period == "daily":
        start_dt = now - timedelta(days=1)
    elif period == "weekly":
        start_dt = now - timedelta(days=7)
    elif period == "monthly":
        start_dt = now - timedelta(days=30)

    # -------- active post condition
    active_post_cond = sa_and(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        sa_or(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now_sql),
        sa_or(Posts.expiration_at.is_(None), Posts.expiration_at > now_sql),
    )

    PAYMENT_SUCCEEDED = PaymentStatus.SUCCEEDED
    ORDER_TYPE_PLAN = PaymentType.PLAN
    ORDER_TYPE_PRICE = PaymentType.SINGLE
    MIN_PAYMENT_PRICE = min_payment_price

    # =====================================================
    # purchase_count per creator (price + plan)
    # =====================================================
    base_payment_cond = sa_and(
        Payments.status == PAYMENT_SUCCEEDED,
        Payments.payment_price >= MIN_PAYMENT_PRICE,
        Payments.paid_at.isnot(None),
    )
    if start_dt is not None:
        base_payment_cond = sa_and(base_payment_cond, Payments.paid_at >= start_dt)

    price_purchase_creator_sq = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .select_from(Prices)
        .join(Posts, sa_and(Posts.id == Prices.post_id, active_post_cond))
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PRICE,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == Prices.id,
                base_payment_cond,
            ),
        )
        .group_by(Posts.creator_user_id)
        .subquery("price_purchase_creator_sq")
    )

    plan_purchase_creator_sq = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .select_from(PostPlans)
        .join(Posts, sa_and(Posts.id == PostPlans.post_id, active_post_cond))
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PLAN,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == PostPlans.plan_id,
                base_payment_cond,
            ),
        )
        .group_by(Posts.creator_user_id)
        .subquery("plan_purchase_creator_sq")
    )

    union_purchase_sq = (
        db.query(
            price_purchase_creator_sq.c.creator_user_id.label("creator_user_id"),
            price_purchase_creator_sq.c.purchase_count.label("purchase_count"),
        )
        .union_all(
            db.query(
                plan_purchase_creator_sq.c.creator_user_id.label("creator_user_id"),
                plan_purchase_creator_sq.c.purchase_count.label("purchase_count"),
            )
        )
        .subquery("union_purchase_sq")
    )

    purchase_creator_sq = (
        db.query(
            union_purchase_sq.c.creator_user_id.label("creator_user_id"),
            func.sum(union_purchase_sq.c.purchase_count).label("purchase_count"),
        )
        .group_by(union_purchase_sq.c.creator_user_id)
        .subquery("purchase_creator_sq")
    )

    # =====================================================
    # bookmark_count per creator (for ordering)
    # =====================================================
    bookmark_q = (
        db.query(
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Bookmarks.user_id)).label("bookmark_count"),
        )
        .select_from(Bookmarks)
        .join(Posts, sa_and(Posts.id == Bookmarks.post_id, active_post_cond))
    )
    if start_dt is not None:
        bookmark_q = bookmark_q.filter(Bookmarks.created_at >= start_dt)

    bookmark_creator_sq = bookmark_q.group_by(Posts.creator_user_id).subquery(
        "bookmark_creator_sq"
    )

    # =====================================================
    # followers_count (all time)
    # =====================================================
    followers_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_agg")
    )

    # =====================================================
    # viewer follow map
    # =====================================================
    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    # -------- pagination
    offset = (page - 1) * limit
    if offset < 0:
        offset = 0

    q = (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.coalesce(followers_agg.c.followers_count, 0).label("followers_count"),
            # compatibility: expose purchase as likes_count so your mapping stays the same
            func.coalesce(purchase_creator_sq.c.purchase_count, 0).label("likes_count"),
            is_following_col,
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(
            purchase_creator_sq, purchase_creator_sq.c.creator_user_id == Users.id
        )
        .outerjoin(
            bookmark_creator_sq, bookmark_creator_sq.c.creator_user_id == Users.id
        )
        .filter(Users.role == AccountType.CREATOR)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )

    rows = (
        q.order_by(
            func.coalesce(purchase_creator_sq.c.purchase_count, 0).desc(),
            func.coalesce(bookmark_creator_sq.c.bookmark_count, 0).desc(),
            func.coalesce(followers_agg.c.followers_count, 0).desc(),
            Users.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return rows


def get_ranking_creators_categories_overall(
    db: Session,
    limit_per_category: int = 6,
    period: str = "all_time",
    top_n_categories: int = 10,
    current_user=None,
    min_payment_price: int = 500,
):
    """
    Creator ranking by category (overall UI)
    Ranking per category:
      purchase_count DESC
      bookmark_count DESC
      followers_count DESC
      Users.id DESC

    Return shape compatible with old output:
      category_id, category_name, creator_user_id,
      profile_name, offical_flg, username, avatar_url, cover_url,
      likes_count (=purchase_count), followers_count, is_following, rn
    """

    # ---------- period window
    now = datetime.now(timezone.utc)
    start_dt = None
    if period == "daily":
        start_dt = now - timedelta(days=1)
    elif period == "weekly":
        start_dt = now - timedelta(days=7)
    elif period == "monthly":
        start_dt = now - timedelta(days=30)

    # ---------- active post condition
    now_sql = func.now()
    active_post_cond = sa_and(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        sa_or(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now_sql),
        sa_or(Posts.expiration_at.is_(None), Posts.expiration_at > now_sql),
    )

    PAYMENT_SUCCEEDED = PaymentStatus.SUCCEEDED
    ORDER_TYPE_PLAN = PaymentType.PLAN
    ORDER_TYPE_PRICE = PaymentType.SINGLE
    MIN_PAYMENT_PRICE = min_payment_price

    # ---------- base payment condition
    base_payment_cond = sa_and(
        Payments.status == PAYMENT_SUCCEEDED,
        Payments.payment_price >= MIN_PAYMENT_PRICE,
        Payments.paid_at.isnot(None),
    )
    if start_dt is not None:
        base_payment_cond = sa_and(base_payment_cond, Payments.paid_at >= start_dt)

    # =====================================================
    # A) purchase_count per (category, creator)
    # =====================================================

    # price payments -> (category, creator)
    price_purchase_cat_creator_sq = (
        db.query(
            PostCategories.category_id.label("category_id"),
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .select_from(Prices)
        .join(Posts, sa_and(Posts.id == Prices.post_id, active_post_cond))
        .join(PostCategories, PostCategories.post_id == Posts.id)
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PRICE,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == Prices.id,
                base_payment_cond,
            ),
        )
        .group_by(PostCategories.category_id, Posts.creator_user_id)
        .subquery("price_purchase_cat_creator_sq")
    )

    # plan payments -> (category, creator)
    plan_purchase_cat_creator_sq = (
        db.query(
            PostCategories.category_id.label("category_id"),
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .select_from(PostPlans)
        .join(Posts, sa_and(Posts.id == PostPlans.post_id, active_post_cond))
        .join(PostCategories, PostCategories.post_id == Posts.id)
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PLAN,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == PostPlans.plan_id,
                base_payment_cond,
            ),
        )
        .group_by(PostCategories.category_id, Posts.creator_user_id)
        .subquery("plan_purchase_cat_creator_sq")
    )

    union_purchase_sq = (
        db.query(
            price_purchase_cat_creator_sq.c.category_id.label("category_id"),
            price_purchase_cat_creator_sq.c.creator_user_id.label("creator_user_id"),
            price_purchase_cat_creator_sq.c.purchase_count.label("purchase_count"),
        )
        .union_all(
            db.query(
                plan_purchase_cat_creator_sq.c.category_id.label("category_id"),
                plan_purchase_cat_creator_sq.c.creator_user_id.label("creator_user_id"),
                plan_purchase_cat_creator_sq.c.purchase_count.label("purchase_count"),
            )
        )
        .subquery("union_purchase_sq")
    )

    purchase_cat_creator_sq = (
        db.query(
            union_purchase_sq.c.category_id.label("category_id"),
            union_purchase_sq.c.creator_user_id.label("creator_user_id"),
            func.sum(union_purchase_sq.c.purchase_count).label("purchase_count"),
        )
        .group_by(union_purchase_sq.c.category_id, union_purchase_sq.c.creator_user_id)
        .subquery("purchase_cat_creator_sq")
    )

    # =====================================================
    # B) bookmark_count per (category, creator)
    # =====================================================
    bookmark_q = (
        db.query(
            PostCategories.category_id.label("category_id"),
            Posts.creator_user_id.label("creator_user_id"),
            func.count(func.distinct(Bookmarks.user_id)).label("bookmark_count"),
        )
        .select_from(Bookmarks)
        .join(Posts, sa_and(Posts.id == Bookmarks.post_id, active_post_cond))
        .join(PostCategories, PostCategories.post_id == Posts.id)
    )
    if start_dt is not None:
        bookmark_q = bookmark_q.filter(Bookmarks.created_at >= start_dt)

    bookmark_cat_creator_sq = bookmark_q.group_by(
        PostCategories.category_id, Posts.creator_user_id
    ).subquery("bookmark_cat_creator_sq")

    # =====================================================
    # C) top categories by total purchases (fallback: total bookmarks)
    # =====================================================
    # category_total_purchases
    cat_total_sq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            func.coalesce(
                func.sum(func.coalesce(purchase_cat_creator_sq.c.purchase_count, 0)), 0
            ).label("category_total_purchases"),
            func.coalesce(
                func.sum(func.coalesce(bookmark_cat_creator_sq.c.bookmark_count, 0)), 0
            ).label("category_total_bookmarks"),
        )
        .select_from(Categories)
        .outerjoin(
            purchase_cat_creator_sq,
            purchase_cat_creator_sq.c.category_id == Categories.id,
        )
        .outerjoin(
            bookmark_cat_creator_sq,
            bookmark_cat_creator_sq.c.category_id == Categories.id,
        )
        .group_by(Categories.id, Categories.name)
        .order_by(
            desc("category_total_purchases"),
            desc("category_total_bookmarks"),
            Categories.id.desc(),
        )
        .limit(top_n_categories)
        .subquery("top_categories_sq")
    )

    # =====================================================
    # D) followers_count + viewer follow map
    # =====================================================
    followers_count_agg = (
        db.query(
            Follows.creator_user_id.label("creator_user_id"),
            func.count(distinct(Follows.follower_user_id)).label("followers_count"),
        )
        .group_by(Follows.creator_user_id)
        .subquery("followers_count_agg")
    )

    if current_user is not None:
        viewer_follow_map = (
            db.query(
                Follows.creator_user_id.label("creator_user_id"),
                literal(True).label("is_following"),
            )
            .filter(Follows.follower_user_id == str(current_user.id))
            .subquery("viewer_follow_map")
        )
        is_following_col = func.coalesce(viewer_follow_map.c.is_following, False).label(
            "is_following"
        )
    else:
        viewer_follow_map = None
        is_following_col = literal(False).label("is_following")

    # =====================================================
    # E) eligible creators in category (must have at least 1 active post in that category)
    # =====================================================
    eligible_creator_sq = (
        db.query(
            PostCategories.category_id.label("category_id"),
            Posts.creator_user_id.label("creator_user_id"),
        )
        .select_from(PostCategories)
        .join(Posts, sa_and(Posts.id == PostCategories.post_id, active_post_cond))
        .distinct()
        .subquery("eligible_creator_sq")
    )

    # =====================================================
    # F) build ranking rows (row_number per category)
    # =====================================================
    q = (
        db.query(
            cat_total_sq.c.category_id,
            cat_total_sq.c.category_name,
            eligible_creator_sq.c.creator_user_id,
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            Profiles.cover_url.label("cover_url"),
            # keep key name "likes_count" for compatibility => purchase_count
            func.coalesce(purchase_cat_creator_sq.c.purchase_count, 0).label(
                "likes_count"
            ),
            func.coalesce(followers_count_agg.c.followers_count, 0).label(
                "followers_count"
            ),
            is_following_col,
            func.row_number()
            .over(
                partition_by=cat_total_sq.c.category_id,
                order_by=(
                    func.coalesce(purchase_cat_creator_sq.c.purchase_count, 0).desc(),
                    func.coalesce(bookmark_cat_creator_sq.c.bookmark_count, 0).desc(),
                    func.coalesce(followers_count_agg.c.followers_count, 0).desc(),
                    Users.created_at.desc(),
                    Users.id.desc(),
                ),
            )
            .label("rn"),
        )
        .select_from(cat_total_sq)
        .join(
            eligible_creator_sq,
            eligible_creator_sq.c.category_id == cat_total_sq.c.category_id,
        )
        .join(Users, Users.id == eligible_creator_sq.c.creator_user_id)
        .join(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            purchase_cat_creator_sq,
            sa_and(
                purchase_cat_creator_sq.c.category_id == cat_total_sq.c.category_id,
                purchase_cat_creator_sq.c.creator_user_id
                == eligible_creator_sq.c.creator_user_id,
            ),
        )
        .outerjoin(
            bookmark_cat_creator_sq,
            sa_and(
                bookmark_cat_creator_sq.c.category_id == cat_total_sq.c.category_id,
                bookmark_cat_creator_sq.c.creator_user_id
                == eligible_creator_sq.c.creator_user_id,
            ),
        )
        .outerjoin(
            followers_count_agg,
            followers_count_agg.c.creator_user_id
            == eligible_creator_sq.c.creator_user_id,
        )
        .filter(Users.role == AccountType.CREATOR)
    )

    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map,
            viewer_follow_map.c.creator_user_id
            == eligible_creator_sq.c.creator_user_id,
        )

    # if start_dt is not None:
    #     q = q.filter(
    #         sa_or(
    #             func.coalesce(purchase_cat_creator_sq.c.purchase_count, 0) > 0,
    #             func.coalesce(bookmark_cat_creator_sq.c.bookmark_count, 0) > 0,
    #         )
    #     )

    ranked_sq = q.subquery("ranked_creators")

    result = (
        db.query(ranked_sq)
        .filter(ranked_sq.c.rn <= limit_per_category)
        .order_by(
            ranked_sq.c.category_name,
            ranked_sq.c.rn.asc(),
        )
        .all()
    )

    return result
