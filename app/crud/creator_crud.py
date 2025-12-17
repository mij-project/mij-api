from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import distinct, literal, or_, select, func, and_
from uuid import UUID
from datetime import datetime, timedelta, timezone
from app.models import Categories, PostCategories
from app.models.creators import Creators
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
)
from app.models.profiles import Profiles
from sqlalchemy import desc
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
        .join(
            PostCategories,
            and_(
                PostCategories.post_id == Posts.id,
                PostCategories.category_id == category,
            ),
        )
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
        .select_from(Users)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(followers_agg, followers_agg.c.creator_user_id == Users.id)
        .outerjoin(likes_agg, likes_agg.c.creator_user_id == Users.id)
        .filter(Users.role == AccountType.CREATOR)
    )
    if viewer_follow_map is not None:
        q = q.outerjoin(
            viewer_follow_map, viewer_follow_map.c.creator_user_id == Users.id
        )

    q = q.filter(likes_agg.c.creator_user_id.isnot(None))
    if filter_date_condition is not None:
        q = q.filter(func.coalesce(likes_agg.c.likes_count, 0) > 0)

    return q.order_by(desc("likes_count")).offset(offset).limit(limit).all()


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
