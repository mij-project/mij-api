import math
import os
from fastapi import HTTPException
from sqlalchemy.orm import Session, aliased
from sqlalchemy import (
    cast,
    distinct,
    func,
    desc,
    and_,
    BigInteger,
    union_all,
    Text,
    or_,
    case,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql.expression import or_ as sa_or, and_ as sa_and
from app.crud.push_noti_crud import push_notification_to_user
from app.crud.subscriptions_crud import check_viewing_rights
from app.crud.time_sale_crud import (
    get_active_plan_timesale_map,
    get_active_price_timesale,
    get_active_price_timesale_pairs,
    get_post_sale_flag_map,
)
from app.models import Payments, UserSettings
from app.models.genres import Genres
from app.models.notifications import Notifications
from app.models.posts import Posts
from app.models.social import Follows, Likes, Bookmarks, Comments
from uuid import UUID
from datetime import datetime, timezone, timedelta
from app.constants.enums import (
    AccountType,
    PaymentStatus,
    PaymentType,
    PostStatus,
    MediaAssetKind,
    MediaAssetStatus,
)
from app.crud.user_crud import check_super_user
from app.schemas.notification import NotificationType
from app.models.post_categories import PostCategories
from app.models.categories import Categories
from typing import List, Dict, Any
from app.models.user import Users
from app.models.profiles import Profiles
from app.models.media_assets import MediaAssets
from app.models.plans import Plans, PostPlans
from app.models.prices import Prices
from app.models.media_rendition_jobs import MediaRenditionJobs
from app.models.subscriptions import Subscriptions
from app.constants.enums import PostType, SubscriptionType, SubscriptionStatus
from app.schemas.user_settings import UserSettingsType
from app.services.email.send_email import (
    send_post_approval_email,
    send_post_rejection_email,
)
from app.services.s3.presign import presign_get
from app.core.logger import Logger

logger = Logger.get_logger()
# エイリアスを定義
ThumbnailAssets = aliased(MediaAssets)
VideoAssets = aliased(MediaAssets)
# ========== 投稿管理 ==========

MEDIA_CDN_URL = os.getenv("MEDIA_CDN_URL")
CDN_BASE_URL = os.getenv("CDN_BASE_URL")

POST_APPROVED_MD = """## mijfans 投稿の審査が完了しました

-name- 様

投稿の審査が完了いたしました。

> ✅ **審査結果: 承認**  
> おめでとうございます！投稿が承認されました。

[投稿を確認する](--post-url--)

すぐに公開しましょう。  
ご不明な点がございましたら、サポートまでお問い合わせください。
"""

POST_REJECTED_MD = """## mijfans 投稿の審査が完了しました

-name- 様

投稿の審査が完了いたしました。

> ❌ **審査結果: 拒否**  
> 誠に申し訳ございませんが、今回の投稿は承認されませんでした。

[投稿を確認する](--post-url--)

再度確認の上、再度申請をお願いいたします。  
ご不明な点がございましたら、サポートまでお問い合わせください。
"""


# ========== 取得系 ==========
def get_total_likes_by_user_id(db: Session, user_id: UUID) -> int:
    """
    ユーザーの投稿についた総合いいね数を取得
    """

    # いいねテーブルと結合していいね数を取得
    total_likes = (
        db.query(func.count(Likes.post_id))
        .join(Posts, Likes.post_id == Posts.id)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))  # 削除されていない投稿のみ
        .scalar()
    )

    return total_likes or 0


def get_posts_count_by_user_id(db: Session, user_id: UUID) -> dict:
    """
    各ステータスの投稿数を取得
    """

    # 審査中
    peding_posts_count = (
        db.query(Posts)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(
            Posts.status.in_(
                [PostStatus.PENDING, PostStatus.RESUBMIT, PostStatus.CONVERTING]
            )
        )
        .count()
    )

    # 修正
    rejected_posts_count = (
        db.query(Posts)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.REJECTED)
        .count()
    )

    # 非公開
    unpublished_posts_count = (
        db.query(Posts)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.UNPUBLISHED)
        .count()
    )

    # 削除
    deleted_posts_count = (
        db.query(Posts)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.DELETED)
        .count()
    )

    # 公開
    approved_posts_count = (
        db.query(Posts)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= func.now()))
        .count()
    )
    # 予約された投稿数
    reserved_posts_count = (
        db.query(Posts)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.scheduled_at.is_not(None))
        .filter(Posts.scheduled_at > func.now())
        .count()
    )

    return {
        "peding_posts_count": peding_posts_count,
        "rejected_posts_count": rejected_posts_count,
        "unpublished_posts_count": unpublished_posts_count,
        "deleted_posts_count": deleted_posts_count,
        "approved_posts_count": approved_posts_count,
        "reserved_posts_count": reserved_posts_count,
    }


def get_posts_by_category_slug(
    db: Session, slug: str, page: int = 1, per_page: int = 100
) -> List[Posts]:
    """
    カテゴリーに紐づく投稿を取得
    """
    offset = (page - 1) * per_page
    limit = per_page
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Categories.slug.label("category_slug"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            Likes.post_id == Posts.id,
        )
        .group_by(
            Categories.id,
            Categories.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .subquery("like_counts")
    )
    total = (
        db.query(func.count(like_counts_subq.c.post_id))
        .filter(like_counts_subq.c.category_slug == slug)
        .count()
    )

    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.category_slug == slug)
        .order_by(
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    post_ids = [row.post_id for row in result]
    post_sale_map = get_post_sale_flag_map(db, post_ids)

    return result, total, post_sale_map


def _build_post_status_query(
    db: Session, user_id: UUID, post_statuses: List[PostStatus]
):
    """
    投稿ステータス取得クエリの共通部分
    """
    VideoAsset = aliased(MediaAssets)
    price_purchase_sq = (
        db.query(
            Prices.post_id.label("post_id"),
            func.count(func.distinct(Payments.id)).label("price_purchase_count"),
        )
        .join(
            Payments,
            (Payments.order_type == 1)
            & (cast(Payments.order_id, PG_UUID(as_uuid=True)) == Prices.id),
        )
        .filter(Payments.status == PaymentStatus.SUCCEEDED)
        .group_by(Prices.post_id)
    ).subquery()

    return (
        db.query(
            Posts,
            func.count(func.distinct(Likes.user_id)).label("likes_count"),
            func.count(func.distinct(Comments.id)).label("comments_count"),
            (
                func.coalesce(price_purchase_sq.c.price_purchase_count, 0)
            )
            .cast(BigInteger)
            .label("purchase_count"),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label("post_price"),
            func.min(Prices.currency).label("post_currency"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAsset.duration_sec,
            func.count(func.distinct(PostPlans.plan_id)).label("plan_count"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAsset,
            (Posts.id == VideoAsset.post_id)
            & (VideoAsset.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .outerjoin(Prices, Posts.id == Prices.post_id)
        .outerjoin(PostPlans, Posts.id == PostPlans.post_id)
        .outerjoin(price_purchase_sq, price_purchase_sq.c.post_id == Posts.id)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status.in_(post_statuses))
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAsset.duration_sec,
            price_purchase_sq.c.price_purchase_count,
        )
        .order_by(desc(Posts.created_at))
    )


def get_post_status_by_user_id(db: Session, user_id: UUID) -> dict:
    """
    ユーザーの投稿ステータスを取得
    """

    # 審査中の投稿を取得
    pending_posts = _build_post_status_query(
        db, user_id, [PostStatus.PENDING, PostStatus.RESUBMIT, PostStatus.CONVERTING]
    ).all()

    # 拒否された投稿を取得
    rejected_posts = _build_post_status_query(db, user_id, [PostStatus.REJECTED]).all()

    # 非公開の投稿を取得
    unpublished_posts = _build_post_status_query(
        db, user_id, [PostStatus.UNPUBLISHED]
    ).all()

    # 削除された投稿を取得
    deleted_posts = _build_post_status_query(db, user_id, [PostStatus.DELETED]).all()

    approved_posts = _build_post_status_query(db, user_id, [PostStatus.APPROVED]).all()

    # 公開された投稿を取得
    approved = []
    # 予約された投稿を取得
    reserved = []
    now = datetime.now(timezone.utc)
    for post in approved_posts:
        if (
            post.Posts.scheduled_at
            and post.Posts.scheduled_at.replace(tzinfo=timezone.utc) > now
        ):
            reserved.append(post)
        else:
            approved.append(post)

    return {
        "pending_posts": pending_posts,
        "rejected_posts": rejected_posts,
        "unpublished_posts": unpublished_posts,
        "deleted_posts": deleted_posts,
        "approved_posts": approved,
        "reserved_posts": reserved,
    }


def get_post_detail_by_id(db: Session, post_id: str, user_id: str | None) -> dict:
    """
    投稿詳細を取得（メディア情報とクリエイター情報、カテゴリ情報、販売情報を含む）
    """
    # 投稿とクリエイター情報を取得
    post, creator, creator_profile = _get_post_and_creator_info(db, post_id)
    if not post:
        return None

    # 各種情報を取得
    categories = _get_post_categories(db, post_id)
    sale_info = _get_sale_info(db, post_id)
    media_info = _get_media_info(db, post_id, user_id)

    # 結果を統合して返却
    return {
        "post": post,
        "creator": creator,
        "creator_profile": creator_profile,
        "categories": categories,
        "price": sale_info["price"],
        "plans": sale_info["plans"],
        "plan_timesale_map": sale_info["plan_timesale_map"],
        **media_info,
    }


def get_posts_by_plan_id(db: Session, plan_id: UUID, user_id: UUID) -> List[tuple]:
    """
    プランに紐づく投稿一覧を取得
    ユーザーがそのプランを購入しているか確認してから返す
    """
    ThumbnailAssets = aliased(MediaAssets)

    # ユーザーがこのプランを購入しているか確認
    purchase = False

    if not purchase:
        return []

    # プランに紐づく投稿を取得
    return (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label("thumbnail_key"),
            ThumbnailAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label("likes_count"),
            func.count(func.distinct(Comments.id)).label("comments_count"),
            Posts.created_at,
        )
        .join(PostPlans, Posts.id == PostPlans.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            ThumbnailAssets,
            (Posts.id == ThumbnailAssets.post_id)
            & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .filter(
            PostPlans.plan_id == plan_id,
            Posts.deleted_at.is_(None),
            Posts.status == PostStatus.APPROVED,
        )
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
            Posts.created_at,
        )
        .order_by(Posts.created_at.desc())
        .all()
    )


# def get_post_by_id(db: Session, post_id: UUID) -> Posts:
#     """
#     投稿をIDで取得
#     """
#     return db.query(Posts).filter(Posts.id == post_id).first()

# ========== いいねした投稿用 ==========


def get_liked_posts_by_user_id(
    db: Session, user_id: UUID, limit: int = 50
) -> List[tuple]:
    """
    ユーザーがいいねした投稿を取得（top_crud.pyの121-126行目の項目と合わせる）
    """
    posts = (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label("thumbnail_key"),
            ThumbnailAssets.duration_sec.label("duration_sec"),
            Likes.created_at.label("created_at"),
            Prices.id.label("price_id"),
            Prices.price.label("post_price"),
            Prices.currency.label("post_currency"),
        )
        .join(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            ThumbnailAssets,
            (Posts.id == ThumbnailAssets.post_id)
            & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(Prices, Posts.id == Prices.post_id)
        .filter(Likes.user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)  # 公開済みの投稿のみ
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
            Likes.created_at,
            Prices.id,
            Prices.price,
            Prices.currency,
        )
        .order_by(desc(Likes.created_at))  # いいねした日時の新しい順
        .limit(limit)
        .all()
    )

    post_ids = [row[0].id for row in posts]
    post_plan_rows = (
        db.query(PostPlans.post_id, PostPlans.plan_id)
        .filter(PostPlans.post_id.in_(post_ids))
        .all()
    )
    post_to_plan_ids: dict[str, list[str]] = {}
    all_plan_ids = set()
    for post_id, plan_id in post_plan_rows:
        post_to_plan_ids.setdefault(str(post_id), []).append(str(plan_id))
        all_plan_ids.add(plan_id)
    plan_ts_map = get_active_plan_timesale_map(db, all_plan_ids)

    price_pairs = []
    for row in posts:
        post_obj = row[0]
        price_id = row.price_id
        price = row.post_price
        if price_id and price and int(price) > 0:
            price_pairs.append((post_obj.id, price_id))

    active_price_pairs = get_active_price_timesale_pairs(db, price_pairs)
    post_sale_map: dict[str, bool] = {}

    for row in posts:
        post_obj = row[0]
        pid = str(post_obj.id)

        # price sale
        has_price_sale = False
        if row.price_id and row.post_price and int(row.post_price) > 0:
            has_price_sale = (pid, str(row.price_id)) in active_price_pairs

        # plan sale
        has_plan_sale = False
        plan_ids = post_to_plan_ids.get(pid, [])
        for plan_id in plan_ids:
            if (
                (plan_id in plan_ts_map)
                and (plan_ts_map[plan_id]["is_active"])
                and (not plan_ts_map[plan_id]["is_expired"])
            ):
                has_plan_sale = True
                break

        post_sale_map[pid] = has_price_sale or has_plan_sale

    for row in posts:
        id = str(row[0].id)
        if id in post_sale_map and post_sale_map[id]:
            is_time_sale = True
        else:
            is_time_sale = False
        sale_percentage = None
        end_date = None
        price_ts = [x for x in active_price_pairs if x[0] == id]
        if price_ts:
            sale_percentage = price_ts[0][2]
            end_date = price_ts[0][3]
        row[0].is_time_sale = is_time_sale
        row[0].price_sale_percentage = sale_percentage
        row[0].price_sale_end_date = end_date

    return posts


def get_bookmarked_posts_by_user_id(db: Session, user_id: UUID) -> List[tuple]:
    """
    ユーザーがブックマークした投稿を取得
    """
    posts = (
        db.query(
            Posts,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label("thumbnail_key"),
            ThumbnailAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label("likes_count"),
            func.count(func.distinct(Comments.id)).label("comments_count"),
            func.min(Prices.price).label("post_price"),
            func.min(Prices.currency).label("post_currency"),
            Bookmarks.created_at.label("bookmarked_at"),
            Prices.id.label("price_id"),
        )
        .join(Bookmarks, Posts.id == Bookmarks.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            ThumbnailAssets,
            (Posts.id == ThumbnailAssets.post_id)
            & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .outerjoin(Prices, Posts.id == Prices.post_id)
        .filter(Bookmarks.user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
            Bookmarks.created_at,
            Prices.id,
        )
        .order_by(desc(Bookmarks.created_at))
        .all()
    )

    post_ids = [row[0].id for row in posts]
    post_plan_rows = (
        db.query(PostPlans.post_id, PostPlans.plan_id)
        .filter(PostPlans.post_id.in_(post_ids))
        .all()
    )
    post_to_plan_ids: dict[str, list[str]] = {}
    all_plan_ids = set()
    for post_id, plan_id in post_plan_rows:
        post_to_plan_ids.setdefault(str(post_id), []).append(str(plan_id))
        all_plan_ids.add(plan_id)
    plan_ts_map = get_active_plan_timesale_map(db, all_plan_ids)

    price_pairs = []
    for row in posts:
        post_obj = row[0]
        price_id = row.price_id
        price = row.post_price
        if price_id and price and int(price) > 0:
            price_pairs.append((post_obj.id, price_id))

    active_price_pairs = get_active_price_timesale_pairs(db, price_pairs)
    post_sale_map: dict[str, bool] = {}

    for row in posts:
        post_obj = row[0]
        pid = str(post_obj.id)

        # price sale
        has_price_sale = False
        if row.price_id and row.post_price and int(row.post_price) > 0:
            has_price_sale = (pid, str(row.price_id)) in active_price_pairs

        # plan sale
        has_plan_sale = False
        plan_ids = post_to_plan_ids.get(pid, [])
        for plan_id in plan_ids:
            if (
                (plan_id in plan_ts_map)
                and (plan_ts_map[plan_id]["is_active"])
                and (not plan_ts_map[plan_id]["is_expired"])
            ):
                has_plan_sale = True
                break

        post_sale_map[pid] = has_price_sale or has_plan_sale

    for row in posts:
        id = str(row[0].id)
        if id in post_sale_map and post_sale_map[id]:
            is_time_sale = True
        else:
            is_time_sale = False
        sale_percentage = None
        end_date = None
        price_ts = [x for x in active_price_pairs if x[0] == id]
        if price_ts:
            sale_percentage = price_ts[0][2]
            end_date = price_ts[0][3]
        row[0].is_time_sale = is_time_sale
        row[0].price_sale_percentage = sale_percentage
        row[0].price_sale_end_date = end_date

    return posts


def get_liked_posts_list_by_user_id(db: Session, user_id: UUID) -> List[tuple]:
    """
    ユーザーがいいねした投稿一覧を取得（カード表示用）
    """
    posts = (
        db.query(
            Posts,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label("thumbnail_key"),
            ThumbnailAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label("likes_count"),
            func.count(func.distinct(Comments.id)).label("comments_count"),
            func.min(Prices.price).label("post_price"),
            func.min(Prices.currency).label("post_currency"),
            Likes.created_at.label("liked_at"),
            Prices.id.label("price_id"),
        )
        .join(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            ThumbnailAssets,
            (Posts.id == ThumbnailAssets.post_id)
            & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .outerjoin(Prices, Posts.id == Prices.post_id)
        .filter(Likes.user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .group_by(
            Posts.id,
            Prices.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
            Likes.created_at,
        )
        .order_by(desc(Likes.created_at))
        .all()
    )
    post_ids = [row[0].id for row in posts]
    post_plan_rows = (
        db.query(PostPlans.post_id, PostPlans.plan_id)
        .filter(PostPlans.post_id.in_(post_ids))
        .all()
    )
    post_to_plan_ids: dict[str, list[str]] = {}
    all_plan_ids = set()
    for post_id, plan_id in post_plan_rows:
        post_to_plan_ids.setdefault(str(post_id), []).append(str(plan_id))
        all_plan_ids.add(plan_id)
    plan_ts_map = get_active_plan_timesale_map(db, all_plan_ids)

    price_pairs = []
    for row in posts:
        post_obj = row[0]
        price_id = row.price_id
        price = row.post_price
        if price_id and price and int(price) > 0:
            price_pairs.append((post_obj.id, price_id))

    active_price_pairs = get_active_price_timesale_pairs(db, price_pairs)
    post_sale_map: dict[str, bool] = {}

    for row in posts:
        post_obj = row[0]
        pid = str(post_obj.id)

        # price sale
        has_price_sale = False
        if row.price_id and row.post_price and int(row.post_price) > 0:
            has_price_sale = (pid, str(row.price_id)) in active_price_pairs

        # plan sale
        has_plan_sale = False
        plan_ids = post_to_plan_ids.get(pid, [])
        for plan_id in plan_ids:
            if (
                (plan_id in plan_ts_map)
                and (plan_ts_map[plan_id]["is_active"])
                and (not plan_ts_map[plan_id]["is_expired"])
            ):
                has_plan_sale = True
                break

        post_sale_map[pid] = has_price_sale or has_plan_sale

    for row in posts:
        id = str(row[0].id)
        if id in post_sale_map and post_sale_map[id]:
            is_time_sale = True
        else:
            is_time_sale = False
        sale_percentage = None
        end_date = None
        price_ts = [x for x in active_price_pairs if x[0] == id]
        if price_ts:
            sale_percentage = price_ts[0][2]
            end_date = price_ts[0][3]
        row[0].is_time_sale = is_time_sale
        row[0].price_sale_percentage = sale_percentage
        row[0].price_sale_end_date = end_date

    return posts


def get_bought_posts_by_user_id(db: Session, user_id: UUID) -> List[tuple]:
    """
    ユーザーが購入した投稿を取得（有効なsubscription経由）

    購読中のプランまたは単品購入した投稿を取得します。
    - order_type=1: order_id は prices.id → prices.post_id 経由で投稿を取得
    - order_type=2: order_id は plans.id → post_plans 経由で投稿を取得

    有効なsubscriptionのみ対象（access_end がNULLまたは現在日時より後、かつstatus=1）
    """
    now = datetime.now(timezone.utc)

    # 有効なsubscriptionの条件
    valid_subscription_filter = and_(
        Subscriptions.user_id == user_id,
        Subscriptions.status.in_(
            [SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED]
        ),  # active
        or_(Subscriptions.access_end.is_(None), Subscriptions.access_end > now),
    )

    # order_type=1: subscriptions → prices → posts の経路でpost_idとplan_nameを取得
    price_posts_subquery = (
        db.query(
            Prices.post_id.label("post_id"),
            func.cast(None, Text).label("plan_name"),  # 単品購入はplan_name=NULL
        )
        .select_from(Subscriptions)
        .join(
            Prices,
            Prices.id == func.cast(Subscriptions.order_id, PG_UUID(as_uuid=True)),
        )
        .filter(valid_subscription_filter)
        .filter(Subscriptions.order_type == SubscriptionType.PLAN)
    )

    # order_type=2: subscriptions → plans → post_plans → posts の経路でpost_idとplan_nameを取得
    plan_posts_subquery = (
        db.query(
            PostPlans.post_id.label("post_id"),
            Plans.name.label("plan_name"),  # プラン名を取得
        )
        .select_from(Subscriptions)
        .join(
            Plans, Plans.id == func.cast(Subscriptions.order_id, PG_UUID(as_uuid=True))
        )
        .join(PostPlans, PostPlans.plan_id == Plans.id)
        .filter(valid_subscription_filter)
        .filter(Subscriptions.order_type == SubscriptionType.SINGLE)
    )

    # 両方をUNION ALLして（重複は後でGROUP BYで処理）
    purchased_post_ids_subquery = union_all(
        price_posts_subquery, plan_posts_subquery
    ).subquery()

    # メインクエリ: 購入済み投稿の詳細情報を取得
    # 同じpost_idが複数のプランに属する場合、最初に見つかったplan_nameを使用
    return (
        db.query(
            Posts,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label("thumbnail_key"),
            ThumbnailAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label("likes_count"),
            func.count(func.distinct(Comments.id)).label("comments_count"),
            Posts.created_at.label("purchased_at"),  # 投稿の作成日を購入日として使用
            func.max(purchased_post_ids_subquery.c.plan_name).label(
                "plan_name"
            ),  # プラン名を取得
        )
        .select_from(Posts)
        .join(
            purchased_post_ids_subquery,
            Posts.id == purchased_post_ids_subquery.c.post_id,
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            ThumbnailAssets,
            (Posts.id == ThumbnailAssets.post_id)
            & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
        )
        .order_by(Posts.created_at.desc())
        .all()
    )


# ========== トップページ用 ==========


def get_ranking_posts(db: Session, limit: int = 5):
    """
    トップページ用の投稿を取得
    """
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    posts = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)  # 公開済みの投稿のみ
        .filter(Posts.deleted_at.is_(None))  # 削除されていない投稿のみ
        .filter(active_post_cond)
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )
    post_ids = [row[0].id for row in posts]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in posts:
        row[0].is_time_sale = post_sale_map.get(row[0].id, False)
    return posts


def get_recent_posts(db: Session, limit: int = 10):
    """
    ランダムで10件の投稿を取得（いいね数も含む）
    """
    now = func.now()

    active_post_cond = and_(
        Posts.post_type == PostType.VIDEO,
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    # 1) likes_count subquery
    likes_sq = (
        db.query(
            Likes.post_id.label("post_id"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .group_by(Likes.post_id)
        .subquery()
    )

    # 2) Rank post
    ranked_sq = (
        db.query(
            Posts.id.label("post_id"),
            func.row_number()
            .over(
                partition_by=Profiles.user_id,
                order_by=func.random(),
            )
            .label("rn"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(active_post_cond)
        .subquery()
    )

    rows = (
        db.query(
            Posts,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label("thumbnail_key"),
            func.coalesce(likes_sq.c.likes_count, 0).label("likes_count"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .join(ranked_sq, Posts.id == ranked_sq.c.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            ThumbnailAssets,
            (Posts.id == ThumbnailAssets.post_id)
            & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(likes_sq, Posts.id == likes_sq.c.post_id)
        .filter(active_post_cond)
        .filter(ranked_sq.c.rn <= 2)
        .order_by(func.random())
        .limit(limit)
        .all()
    )
    post_ids = [row[0].id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row[0].is_time_sale = post_sale_map.get(row[0].id, False)
    return rows


# ========== ランキング用 集合==========


def get_ranking_posts_overall_all_time(db: Session, limit: int = 500):
    """
    全期間でいいね数が多い投稿を取得
    """
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    rows = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)  # 公開済みの投稿のみ
        .filter(Posts.deleted_at.is_(None))  # 削除されていない投稿のみ
        .filter(active_post_cond)
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )
    post_ids = [row[0].id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row[0].is_time_sale = post_sale_map.get(row[0].id, False)
    return rows


def get_ranking_posts_overall_monthly(db: Session, limit: int = 50):
    """
    月間でいいね数が多い投稿を取得
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    rows = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_month_ago)  # 過去30日以内のいいね
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )
    post_ids = [row[0].id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row[0].is_time_sale = post_sale_map.get(row[0].id, False)
    return rows


def get_ranking_posts_overall_weekly(db: Session, limit: int = 50):
    """
    週間でいいね数が多い投稿を取得
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    rows = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_week_ago)  # 過去7日以内のいいね
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )

    post_ids = [row[0].id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row[0].is_time_sale = post_sale_map.get(row[0].id, False)
    return rows


def get_ranking_posts_overall_daily(db: Session, limit: int = 50):
    """
    日間でいいね数が多い投稿を取得
    """
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    rows = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_day_ago)  # 過去1日以内のいいね
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )
    post_ids = [row[0].id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row[0].is_time_sale = post_sale_map.get(row[0].id, False)
    return rows


# ========== 作成・更新・削除系 ==========
def create_post(db: Session, post_data: dict):
    """
    投稿を作成
    """
    post = Posts(**post_data)
    db.add(post)
    db.flush()
    return post


def update_post(db: Session, post_data: dict):
    """
    投稿を更新
    """
    post = db.query(Posts).filter(Posts.id == post_data["id"]).first()
    if not post:
        return None

    for key, value in post_data.items():
        # idは更新対象外（主キーなので）
        if key == "id":
            continue
        # 属性が存在する場合は値を設定（Noneも含む）
        if hasattr(post, key):
            setattr(post, key, value)

    post.updated_at = datetime.now(timezone.utc)
    db.flush()
    return post


def update_post_media_assets(db: Session, post_id: UUID, key: str, kind: str):
    """
    投稿のメディアアセットを更新
    """
    post = db.query(Posts).filter(Posts.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # kindを整数値にマッピング
    kind_mapping = {
        "ogp": MediaAssetKind.OGP,
        "thumbnail": MediaAssetKind.THUMBNAIL,
        "main": MediaAssetKind.MAIN_VIDEO,
        "sample": MediaAssetKind.SAMPLE_VIDEO,
        "images": MediaAssetKind.IMAGES,
    }

    kind_int = kind_mapping.get(kind)
    if kind_int is None:
        raise HTTPException(status_code=400, detail=f"Unsupported kind: {kind}")

    post.updated_at = datetime.now(timezone.utc)
    db.add(post)
    db.flush()
    return post


def update_post_status(
    db: Session, post_id: UUID, status: int, authenticated_flg: int = None
):
    """
    投稿のステータスを更新
    """
    post = db.query(Posts).filter(Posts.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    post.status = status
    if authenticated_flg is not None:
        post.authenticated_flg = authenticated_flg
    post.updated_at = datetime.now(timezone.utc)
    db.add(post)
    db.flush()
    return post


# ========== 内部関数 ==========


def _get_post_and_creator_info(db: Session, post_id: str) -> tuple:
    """投稿とクリエイター情報を取得"""
    post = db.query(Posts).filter(Posts.id == post_id).first()

    if not post:
        return None, None, None

    creator = db.query(Users).filter(Users.id == post.creator_user_id).first()
    creator_profile = (
        db.query(Profiles).filter(Profiles.user_id == post.creator_user_id).first()
    )

    return post, creator, creator_profile


def _get_post_categories(db: Session, post_id: str) -> list:
    """投稿のカテゴリ情報を取得"""
    return (
        db.query(Categories)
        .join(PostCategories, Categories.id == PostCategories.category_id)
        .filter(PostCategories.post_id == post_id)
        .filter(Categories.is_active.is_(True))
        .all()
    )


def _get_likes_count(db: Session, post_id: str) -> int:
    """投稿のいいね数を取得"""
    return (
        db.query(func.count(Likes.post_id)).filter(Likes.post_id == post_id).scalar()
        or 0
    )


def _get_sale_info(db: Session, post_id: str) -> dict:
    """投稿に紐づく単品情報とプラン金額を取得

    Args:
        db (Session): データベースセッション
        post_id (str): 投稿ID

    Returns:
        dict: 単品売上情報
    """

    # Priceテーブルから金額を取得
    price = db.query(Prices).filter(Prices.post_id == post_id).first()
    if price is not None:
        price.is_time_sale_active = False
        price.time_sale_price = None
        price.sale_percentage = None
        price.end_date = None
    if price:
        price_time_sale = get_active_price_timesale(db, post_id, price.id)
        if (
            price_time_sale
            and price_time_sale["is_active"]
            and (not price_time_sale["is_expired"])
        ):
            sale_price = int(price.price) - math.ceil(
                int(price.price) * price_time_sale["sale_percentage"] / 100
            )
            price.is_time_sale_active = True
            price.time_sale_price = sale_price
            price.sale_percentage = price_time_sale["sale_percentage"]
            price.end_date = price_time_sale["end_date"]
    # Planテーブルからプラン金額を取得（post_plansテーブルを経由）
    plans_query = (
        db.query(Plans)
        .join(PostPlans, Plans.id == PostPlans.plan_id)
        .filter(PostPlans.post_id == post_id)
        .all()
    )
    plan_ids = [plan.id for plan in plans_query]
    plan_timesale_map = get_active_plan_timesale_map(db, plan_ids)
    # プランにサムネイル情報を追加
    plans_with_thumbnails = []
    for plan in plans_query:
        # プランに紐づく投稿のサムネイル画像を取得（最大3枚）
        plan_post_info = (
            db.query(MediaAssets.storage_key, Posts.description)
            .join(Posts, MediaAssets.post_id == Posts.id)
            .join(PostPlans, MediaAssets.post_id == PostPlans.post_id)
            .filter(PostPlans.plan_id == plan.id)
            .filter(MediaAssets.kind == MediaAssetKind.THUMBNAIL)
            .limit(3)
            .all()
        )

        # プランに紐づく投稿の総数を取得（post_plansテーブルから）
        post_count = (
            db.query(func.count(PostPlans.post_id))
            .join(Posts, PostPlans.post_id == Posts.id)
            .filter(
                PostPlans.plan_id == plan.id,
                Posts.deleted_at.is_(None),
                Posts.status == PostStatus.APPROVED,
            )
            .scalar()
            or 0
        )

        plans_with_thumbnails.append(
            {
                "id": plan.id,
                "name": plan.name,
                "description": plan.description,
                "price": plan.price,
                "type": plan.type,
                "open_dm_flg": plan.open_dm_flg,
                "post_count": post_count,
                "plan_post": [
                    {"description": post.description, "thumbnail_url": post.storage_key}
                    for post in plan_post_info
                ],
            }
        )

    return {
        "price": price,
        "plans": plans_with_thumbnails,
        "plan_timesale_map": plan_timesale_map,
    }


def _get_media_info(db: Session, post_id: str, user_id: str | None) -> dict:
    """メディア情報を取得・処理"""
    media_assets = db.query(MediaAssets).filter(MediaAssets.post_id == post_id).all()

    # 視聴権限をチェック
    is_entitlement = check_viewing_rights(db, post_id, user_id)

    # スーパーユーザーかどうかをチェック
    is_super_user = check_super_user(db, user_id)
    if is_super_user:
        is_entitlement = True

    # 視聴権限に応じてメディア種別とファイル名を設定
    set_media_kind = (
        MediaAssetKind.MAIN_VIDEO if is_entitlement else MediaAssetKind.SAMPLE_VIDEO
    )
    set_file_name = "_1080w.webp" if is_entitlement else "_blurred.webp"

    media_info = []
    thumbnail_key = None
    for media_asset in media_assets:
        if media_asset.kind == MediaAssetKind.THUMBNAIL:
            thumbnail_key = f"{CDN_BASE_URL}/{media_asset.storage_key}"
        elif media_asset.kind == MediaAssetKind.IMAGES:
            media_info.append(
                {
                    "kind": media_asset.kind,
                    "duration": media_asset.duration_sec,
                    "media_assets_id": media_asset.id,
                    "orientation": media_asset.orientation,
                    "post_id": media_asset.post_id,
                    "storage_key": f"{MEDIA_CDN_URL}/{media_asset.storage_key}{set_file_name}",
                }
            )
        elif media_asset.kind == set_media_kind:
            media_info.append(
                {
                    "kind": media_asset.kind,
                    "duration": media_asset.duration_sec,
                    "media_assets_id": media_asset.id,
                    "orientation": media_asset.orientation,
                    "post_id": media_asset.post_id,
                    "storage_key": f"{MEDIA_CDN_URL}/{media_asset.storage_key}",
                }
            )

    # for media_asset in media_assets:
    #     if media_asset.kind == MediaAssetKind.MAIN_VIDEO:
    #         main_duration =

    return {
        "media_assets": media_assets,
        "media_info": media_info,
        "thumbnail_key": thumbnail_key,
        "is_entitlement": is_entitlement,
    }


# ========== クリエイター投稿管理用 ==========
def _get_media_info_for_creator(db: Session, post_id: str, status: int) -> dict:
    """クリエイター用メディア情報を取得（視聴権限チェックなし、全メディア取得）"""
    media_assets = db.query(MediaAssets).filter(MediaAssets.post_id == post_id).all()

    sample_video = None
    main_video = None
    thumbnail = None
    ogp_image = None
    images = []
    upload_flg = True if status != PostStatus.APPROVED else False

    for media_asset in media_assets:
        if media_asset.kind == MediaAssetKind.THUMBNAIL:
            thumbnail = {
                "kind": media_asset.kind,
                "storage_key": media_asset.storage_key,
                "url": f"{CDN_BASE_URL}/{media_asset.storage_key}",
            }
        elif media_asset.kind == MediaAssetKind.SAMPLE_VIDEO:
            if upload_flg:
                presign_url = presign_get("ingest", media_asset.storage_key)
                sample_video_url = presign_url["download_url"]
            else:
                sample_video_url = f"{MEDIA_CDN_URL}/{media_asset.storage_key}"

            sample_video = {
                "kind": media_asset.kind,
                "storage_key": media_asset.storage_key,
                "url": sample_video_url,
                "duration": media_asset.duration_sec,
                "reject_comments": media_asset.reject_comments,
            }
        elif media_asset.kind == MediaAssetKind.MAIN_VIDEO:
            if upload_flg:
                presign_url = presign_get("ingest", media_asset.storage_key)
                main_video_url = presign_url["download_url"]
            else:
                main_video_url = f"{MEDIA_CDN_URL}/{media_asset.storage_key}"

            main_video = {
                "kind": media_asset.kind,
                "storage_key": media_asset.storage_key,
                "url": main_video_url,
                "duration": media_asset.duration_sec,
                "reject_comments": media_asset.reject_comments,
            }
        elif media_asset.kind == MediaAssetKind.IMAGES:
            if upload_flg and media_asset.status in [
                MediaAssetStatus.PENDING,
                MediaAssetStatus.RESUBMIT,
                MediaAssetStatus.CONVERTING,
            ]:
                presign_url = presign_get("ingest", media_asset.storage_key)
                image_url = presign_url["download_url"]
            else:
                image_url = f"{MEDIA_CDN_URL}/{media_asset.storage_key}_1080w.webp"
            images.append(
                {
                    "id": str(media_asset.id),  # IDをstringとして返す
                    "kind": media_asset.kind,
                    "storage_key": media_asset.storage_key,
                    "url": image_url,
                    "duration": media_asset.duration_sec,
                    "orientation": media_asset.orientation,
                    "reject_comments": media_asset.reject_comments,
                }
            )
        elif media_asset.kind == MediaAssetKind.OGP:
            ogp_image = {
                "kind": media_asset.kind,
                "storage_key": media_asset.storage_key,
                "url": f"{CDN_BASE_URL}/{media_asset.storage_key}",
                "reject_comments": media_asset.reject_comments,
            }

    return {
        "thumbnail": thumbnail,
        "sample_video": sample_video,
        "main_video": main_video,
        "images": images,
        "ogp_image": ogp_image,
        "media_assets": media_assets,
    }


def get_post_detail_for_creator(
    db: Session, post_id: UUID, creator_user_id: UUID
) -> dict | None:
    """
    クリエイター自身の投稿詳細を取得（統計情報含む）
    """
    VideoAsset = aliased(MediaAssets)
    ThumbnailAsset = aliased(MediaAssets)
    # OGPAsset = aliased(MediaAssets)

    result = (
        db.query(
            Posts,
            func.count(func.distinct(Likes.user_id)).label("likes_count"),
            func.count(func.distinct(Comments.id)).label("comments_count"),
            func.cast(0, BigInteger).label(
                "purchase_count"
            ),  # 仮の値: 決済処理未実装のため0を返す
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label("post_price"),
            func.min(Prices.currency).label("post_currency"),
            ThumbnailAsset.storage_key.label("thumbnail_key"),
            VideoAsset.duration_sec,
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            ThumbnailAsset,
            (Posts.id == ThumbnailAsset.post_id)
            & (ThumbnailAsset.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAsset,
            (Posts.id == VideoAsset.post_id)
            & (VideoAsset.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .outerjoin(Prices, Posts.id == Prices.post_id)
        .filter(Posts.id == post_id)
        .filter(Posts.creator_user_id == creator_user_id)
        .filter(Posts.deleted_at.is_(None))
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAsset.storage_key,
            VideoAsset.duration_sec,
        )
        .first()
    )

    if not result:
        return None

    # 動画時間をフォーマット
    duration = None
    if result.duration_sec:
        minutes = int(result.duration_sec // 60)
        seconds = int(result.duration_sec % 60)
        duration = f"{minutes:02d}:{seconds:02d}"

    # 投稿タイプを判定
    is_video = result.Posts.post_type == PostType.VIDEO  # PostType.VIDEO = 1

    # メディア情報を取得

    return {
        "post": result.Posts,
        "likes_count": result.likes_count or 0,
        "comments_count": result.comments_count or 0,
        "purchase_count": result.purchase_count or 0,
        "creator_name": result.profile_name,
        "username": result.username,
        "creator_avatar_url": result.avatar_url,
        "price": result.post_price or 0,
        "currency": result.post_currency or "JPY",
        "thumbnail_key": result.thumbnail_key,
        "duration": duration,
        "is_video": is_video,
    }


def update_post_by_creator(
    db: Session, post_id: UUID, creator_user_id: UUID, update_data: dict
) -> Posts | None:
    """
    クリエイターが自分の投稿を更新

    Args:
        db: データベースセッション
        post_id: 投稿ID
        creator_user_id: クリエイターのユーザーID
        update_data: 更新データ（status, visibility, scheduled_at, deleted_atなど）

    Returns:
        Posts | None: 更新された投稿、または見つからない場合はNone
    """
    from app.constants.enums import PostStatus

    post = (
        db.query(Posts)
        .filter(Posts.id == post_id)
        .filter(Posts.creator_user_id == creator_user_id)
        .filter(Posts.deleted_at.is_(None))
        .first()
    )

    if not post:
        return None

    # 更新可能なフィールド
    allowed_fields = [
        "description",
        "status",
        "visibility",
        "scheduled_at",
        "expiration_at",
    ]

    for field, value in update_data.items():
        if field in allowed_fields and value is not None:
            setattr(post, field, value)

    # ステータスがDELETEDの場合、deleted_atを設定
    if "status" in update_data and update_data["status"] == PostStatus.DELETED:
        post.deleted_at = datetime.now(timezone.utc)

    post.updated_at = datetime.now(timezone.utc)
    db.flush()

    return post


# ========== ランキング用 各category==========
def get_ranking_creators_overall_all_time(db: Session, limit: int = 500):
    """
    いいね数が多いCreator overalltime
    """
    return (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.count(Follows.creator_user_id).label("followers_count"),
            func.array_agg(Follows.follower_user_id).label("follower_ids"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, Posts.creator_user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .filter(Users.role == AccountType.CREATOR)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )


def get_ranking_creators_overall_daily(db: Session, limit: int = 500):
    """
    いいね数が多いCreator daily
    """
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    return (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.count(Follows.creator_user_id).label("followers_count"),
            func.array_agg(Follows.follower_user_id).label("follower_ids"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, Posts.creator_user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(Likes.created_at >= one_day_ago)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )


def get_ranking_creators_overall_weekly(db: Session, limit: int = 500):
    """
    いいね数が多いCreator weekly
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    return (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.count(Follows.creator_user_id).label("followers_count"),
            func.array_agg(Follows.follower_user_id).label("follower_ids"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, Posts.creator_user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(Likes.created_at >= one_week_ago)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )


def get_ranking_creators_overall_monthly(db: Session, limit: int = 500):
    """
    いいね数が多いCreator monthly
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    return (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.count(Follows.creator_user_id).label("followers_count"),
            func.array_agg(Follows.follower_user_id).label("follower_ids"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, Posts.creator_user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(Likes.created_at >= one_month_ago)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .order_by(desc("likes_count"))
        .limit(limit)
        .all()
    )


def get_ranking_creators_overall_detail_all_time(
    db: Session, page: int = 1, limit: int = 500
):
    """
    いいね数が多いCreator overalltime
    """
    offset = (page - 1) * limit
    return (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.count(Follows.creator_user_id).label("followers_count"),
            func.array_agg(Follows.follower_user_id).label("follower_ids"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, Posts.creator_user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .filter(Users.role == AccountType.CREATOR)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .order_by(desc("likes_count"))
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_ranking_creators_overall_detail_daily(
    db: Session, page: int = 1, limit: int = 500
):
    """
    いいね数が多いCreator daily
    """
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    offset = (page - 1) * limit
    return (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.count(Follows.creator_user_id).label("followers_count"),
            func.array_agg(Follows.follower_user_id).label("follower_ids"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, Posts.creator_user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(Likes.created_at >= one_day_ago)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .order_by(desc("likes_count"))
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_ranking_creators_overall_detail_weekly(
    db: Session, page: int = 1, limit: int = 500
):
    """
    いいね数が多いCreator weekly
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    offset = (page - 1) * limit
    return (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.count(Follows.creator_user_id).label("followers_count"),
            func.array_agg(Follows.follower_user_id).label("follower_ids"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, Posts.creator_user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(Likes.created_at >= one_week_ago)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .order_by(desc("likes_count"))
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_ranking_creators_overall_detail_monthly(
    db: Session, page: int = 1, limit: int = 500
):
    """
    いいね数が多いCreator monthly
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    offset = (page - 1) * limit
    return (
        db.query(
            Users,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            func.count(Follows.creator_user_id).label("followers_count"),
            func.array_agg(Follows.follower_user_id).label("follower_ids"),
            func.count(distinct(Likes.post_id)).label("likes_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, Posts.creator_user_id == Users.id)
        .outerjoin(Likes, Likes.post_id == Posts.id)
        .filter(Users.role == AccountType.CREATOR)
        .filter(Likes.created_at >= one_month_ago)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
        )
        .order_by(desc("likes_count"))
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_post_by_id(db: Session, post_id: str) -> Dict[str, Any]:
    """
    投稿IDをキーにして投稿情報、ユーザー情報、メディア情報を取得
    """

    # 投稿情報と関連データを取得
    result = (
        db.query(
            Posts,
            Users,
            Profiles,
            MediaAssets,
            MediaRenditionJobs.output_key.label("rendition_output_key"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, Posts.id == MediaAssets.post_id)
        .outerjoin(MediaRenditionJobs, MediaAssets.id == MediaRenditionJobs.asset_id)
        .filter(Posts.id == post_id)
        .filter(Posts.deleted_at.is_(None))
        .all()
    )

    if not result:
        return None

    # 最初のレコードから基本情報を取得
    first_row = result[0]
    post = first_row.Posts
    user = first_row.Users
    profile = first_row.Profiles

    # メディアアセット情報を整理
    media_assets = []
    rendition_jobs = []

    for row in result:
        if row.MediaAssets:
            media_asset = {
                "id": str(row.MediaAssets.id),
                "status": row.MediaAssets.status,
                "post_id": str(row.MediaAssets.post_id),
                "kind": row.MediaAssets.kind,
                "storage_key": row.MediaAssets.storage_key,
                "file_size": row.MediaAssets.bytes,
                "reject_comments": row.MediaAssets.reject_comments,
                "duration": float(row.MediaAssets.duration_sec)
                if row.MediaAssets.duration_sec
                else None,
                "duration_sec": float(row.MediaAssets.duration_sec)
                if row.MediaAssets.duration_sec
                else None,
                "orientation": row.MediaAssets.orientation,
                "sample_type": row.MediaAssets.sample_type,
                "sample_start_time": float(row.MediaAssets.sample_start_time)
                if row.MediaAssets.sample_start_time
                else None,
                "sample_end_time": float(row.MediaAssets.sample_end_time)
                if row.MediaAssets.sample_end_time
                else None,
                "created_at": row.MediaAssets.created_at.isoformat()
                if row.MediaAssets.created_at
                else None,
                "updated_at": None,
            }

            # 重複を避けるため、既に存在するかチェック
            if not any(ma["id"] == media_asset["id"] for ma in media_assets):
                media_assets.append(media_asset)

        if row.rendition_output_key:
            rendition_job = {"output_key": row.rendition_output_key}

            # 重複を避けるため、既に存在するかチェック
            if not any(
                rj["output_key"] == rendition_job["output_key"] for rj in rendition_jobs
            ):
                rendition_jobs.append(rendition_job)

    # 価格情報を取得（単品販売）
    single_price_data = (
        db.query(Prices.price)
        .filter(Prices.post_id == post_id, Prices.is_active.is_(True))
        .first()
    )

    # プラン情報を取得
    plan_data = (
        db.query(Plans.id, Plans.name, Plans.price)
        .join(PostPlans, Plans.id == PostPlans.plan_id)
        .filter(
            PostPlans.post_id == post_id,
            Plans.deleted_at.is_(None),
        )
        .all()
    )

    # プラン情報をリスト形式に整形
    plans_list = (
        [
            {"plan_id": str(plan.id), "plan_name": plan.name, "price": plan.price}
            for plan in plan_data
        ]
        if plan_data
        else None
    )

    # 指定された内容を返却
    return {
        # 投稿情報
        "id": str(post.id),
        "description": post.description,
        "status": post.status,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "authenticated_flg": post.authenticated_flg,
        # ユーザー情報
        "user_id": str(user.id),
        "profile_name": user.profile_name,
        # プロフィール情報
        "username": profile.username,
        "profile_avatar_url": f"{CDN_BASE_URL}/{profile.avatar_url}"
        if profile.avatar_url
        else None,
        "post_type": post.post_type,
        # メディアアセット情報
        "media_assets": {
            ma["id"]: {
                "kind": ma["kind"],
                "storage_key": ma["storage_key"],
                "status": ma["status"],
                "reject_comments": ma["reject_comments"],
                "duration_sec": ma.get("duration_sec"),
                "orientation": ma.get("orientation"),
                "sample_type": ma.get("sample_type"),
                "sample_start_time": ma.get("sample_start_time"),
                "sample_end_time": ma.get("sample_end_time"),
            }
            for ma in media_assets
            if ma["storage_key"]
        },  # メディアアセットIDをキー、kindとstorage_keyを含む辞書を値とする辞書
        # 価格情報
        "single_price": single_price_data[0] if single_price_data else None,
        "plans": plans_list,
        # カテゴリー情報
    }


def get_post_and_categories_by_id(db: Session, post_id: str) -> dict:
    """
    投稿IDをキーにして投稿情報、ユーザー情報、メディア情報、カテゴリー情報を取得
    """

    # 投稿情報と関連データを取得
    result = (
        db.query(
            Posts,
            Users,
            Profiles,
            MediaAssets,
            MediaRenditionJobs.output_key.label("rendition_output_key"),
            MediaRenditionJobs.input_key.label("input_key"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, Posts.id == MediaAssets.post_id)
        .outerjoin(MediaRenditionJobs, MediaAssets.id == MediaRenditionJobs.asset_id)
        .filter(Posts.id == post_id)
        .filter(Posts.deleted_at.is_(None))
        .all()
    )

    if not result:
        return None

    # 最初のレコードから基本情報を取得
    first_row = result[0]
    post = first_row.Posts
    user = first_row.Users
    profile = first_row.Profiles

    # メディアアセット情報を整理
    media_assets = []
    rendition_jobs = []

    for row in result:
        if row.MediaAssets:
            media_asset = {
                "id": str(row.MediaAssets.id),
                "status": row.MediaAssets.status,
                "post_id": str(row.MediaAssets.post_id),
                "kind": row.MediaAssets.kind,
                "storage_key": row.MediaAssets.storage_key,
                "file_size": row.MediaAssets.bytes,
                "reject_comments": row.MediaAssets.reject_comments,
                "duration": float(row.MediaAssets.duration_sec)
                if row.MediaAssets.duration_sec
                else None,
                "duration_sec": float(row.MediaAssets.duration_sec)
                if row.MediaAssets.duration_sec
                else None,
                "orientation": row.MediaAssets.orientation,
                "sample_type": row.MediaAssets.sample_type,
                "sample_start_time": float(row.MediaAssets.sample_start_time)
                if row.MediaAssets.sample_start_time
                else None,
                "sample_end_time": float(row.MediaAssets.sample_end_time)
                if row.MediaAssets.sample_end_time
                else None,
                "created_at": row.MediaAssets.created_at.isoformat()
                if row.MediaAssets.created_at
                else None,
                "updated_at": None,
                "input_key": getattr(row, "input_key", None),
            }

            # 重複を避けるため、既に存在するかチェック
            if not any(ma["id"] == media_asset["id"] for ma in media_assets):
                media_assets.append(media_asset)

        if row.rendition_output_key:
            rendition_job = {"output_key": row.rendition_output_key}

            # 重複を避けるため、既に存在するかチェック
            if not any(
                rj["output_key"] == rendition_job["output_key"] for rj in rendition_jobs
            ):
                rendition_jobs.append(rendition_job)

    # 価格情報を取得（単品販売）
    single_price_data = (
        db.query(Prices.price)
        .filter(Prices.post_id == post_id, Prices.is_active.is_(True))
        .first()
    )

    # プラン情報を取得
    plan_data = (
        db.query(Plans.id, Plans.name, Plans.price)
        .join(PostPlans, Plans.id == PostPlans.plan_id)
        .filter(
            PostPlans.post_id == post_id,
            Plans.deleted_at.is_(None),
        )
        .all()
    )

    # プラン情報をリスト形式に整形
    plans_list = (
        [
            {"plan_id": str(plan.id), "plan_name": plan.name, "price": plan.price}
            for plan in plan_data
        ]
        if plan_data
        else None
    )

    # カテゴリー情報を取得
    category_data = (
        db.query(Categories.id, Categories.name, Categories.slug)
        .join(PostCategories, Categories.id == PostCategories.category_id)
        .filter(PostCategories.post_id == post_id)
        .all()
    )

    # カテゴリー情報をリスト形式に整形
    categories_list = (
        [
            {
                "category_id": str(category.id),
                "category_name": category.name,
                "slug": category.slug,
            }
            for category in category_data
        ]
        if category_data
        else None
    )

    # 指定された内容を返却
    return {
        # 投稿情報
        "id": str(post.id),
        "description": post.description,
        "status": post.status,
        "created_at": post.created_at.isoformat() if post.created_at else None,
        "authenticated_flg": post.authenticated_flg,
        # ユーザー情報
        "user_id": str(user.id),
        "profile_name": user.profile_name,
        # プロフィール情報
        "username": profile.username,
        "profile_avatar_url": f"{CDN_BASE_URL}/{profile.avatar_url}"
        if profile.avatar_url
        else None,
        "post_type": post.post_type,
        # メディアアセット情報
        "media_assets": {
            ma["id"]: {
                "kind": ma["kind"],
                "storage_key": ma["storage_key"],
                "status": ma["status"],
                "reject_comments": ma["reject_comments"],
                "duration_sec": ma.get("duration_sec"),
                "orientation": ma.get("orientation"),
                "sample_type": ma.get("sample_type"),
                "sample_start_time": ma.get("sample_start_time"),
                "sample_end_time": ma.get("sample_end_time"),
                "input_key": ma.get("input_key"),
            }
            for ma in media_assets
            if ma["storage_key"]
        },  # メディアアセットIDをキー、kindとstorage_keyを含む辞書を値とする辞書
        # 価格情報
        "single_price": single_price_data[0] if single_price_data else None,
        "plans": plans_list,
        # カテゴリー情報
        "categories": categories_list,
    }


# ========== ランキング用 各ジャンル==========
def get_ranking_posts_detail_categories_all_time(
    db: Session, category: str, page: int = 1, limit: int = 500
):
    """
    全期間でいいね数が多い投稿を取得
    """
    offset = (page - 1) * limit

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
                active_post_cond,
            ),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            Likes.post_id == Posts.id,
        )
        .group_by(
            Categories.id,
            Categories.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .subquery("like_counts")
    )

    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.category_id == category)
        .order_by(
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    post_ids = [row.post_id for row in result]
    post_sale_map = get_post_sale_flag_map(db, post_ids)

    return result, post_sale_map


def get_ranking_posts_detail_categories_daily(
    db: Session, category: str, page: int = 1, limit: int = 500
):
    """
    各ジャンルでいいね数が多い投稿を取得 Daily
    """
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    offset = (page - 1) * limit

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
                active_post_cond,
            ),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_day_ago,
            ),
        )
        .group_by(
            Categories.id,
            Categories.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .subquery("like_counts")
    )

    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.category_id == category)
        .order_by(
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    post_ids = [row.post_id for row in result]
    post_sale_map = get_post_sale_flag_map(db, post_ids)

    return result, post_sale_map


def get_ranking_posts_detail_categories_weekly(
    db: Session, category: str, page: int = 1, limit: int = 500
):
    """
    各ジャンルでいいね数が多い投稿を取得 Weekly
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    offset = (page - 1) * limit

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
                active_post_cond,
            ),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_week_ago,
            ),
        )
        .group_by(
            Categories.id,
            Categories.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .subquery("like_counts")
    )

    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.category_id == category)
        .order_by(
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    post_ids = [row.post_id for row in result]
    post_sale_map = get_post_sale_flag_map(db, post_ids)

    return result, post_sale_map


def get_ranking_posts_detail_categories_monthly(
    db: Session, category: str, page: int = 1, limit: int = 500
):
    """
    各ジャンルでいいね数が多い投稿を取得 Monthy
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    offset = (page - 1) * limit

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
                active_post_cond,
            ),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_month_ago,
            ),
        )
        .group_by(
            Categories.id,
            Categories.name,
            Posts.id.label("post_id"),
            Posts.post_type.label("post_type"),
            Posts.creator_user_id.label("creator_user_id"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .subquery("like_counts")
    )
    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.category_id == category)
        .order_by(
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    post_ids = [row.post_id for row in result]
    post_sale_map = get_post_sale_flag_map(db, post_ids)

    return result, post_sale_map


# ========== ランキング用 各ジャンル==========
def get_ranking_posts_categories_all_time(db: Session, limit: int = 50):
    """
    各カテゴリーでいいね数が多い投稿を取得 All time
    """
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    top_categories_subq = (
        db.query(
            Categories.id.label("category_id"),
            func.count(Likes.post_id).label("total_likes"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                # Likes.created_at >= func.date_trunc("day", func.now()),
            ),
        )
        .group_by(Categories.id)
        .order_by(func.count(Likes.post_id).desc())
        .limit(10)
        .subquery("top_categories")
    )
    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Genres.id.label("genre_id"),
            Genres.name.label("genre_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Users.offical_flg.label("offical_flg"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
            func.row_number()
            .over(partition_by=Categories.id, order_by=func.count(Likes.post_id).desc())
            .label("rn"),
        )
        .select_from(Categories)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == Categories.id,
        )
        .outerjoin(Genres, Categories.genre_id == Genres.id)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(Posts.id == PostCategories.post_id, active_post_cond),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                # Likes.created_at >= func.date_trunc("day", func.now()),
            ),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .group_by(
            Categories.id,
            Categories.name,
            Genres.id,
            Genres.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .subquery("like_counts")
    )

    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.rn <= limit)
        .order_by(
            like_counts_subq.c.category_name,
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .all()
    )

    return result


def get_ranking_posts_categories_daily(db: Session, limit: int = 50):
    """
    各カテゴリーでいいね数が多い投稿を取得 Daily
    """
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    top_categories_subq = (
        db.query(
            Categories.id.label("category_id"),
            func.count(Likes.post_id).label("total_likes"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_day_ago,
            ),
        )
        .group_by(Categories.id)
        .order_by(func.count(Likes.post_id).desc())
        .limit(10)
        .subquery("top_categories")
    )
    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Genres.id.label("genre_id"),
            Genres.name.label("genre_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Users.offical_flg.label("offical_flg"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
            func.row_number()
            .over(partition_by=Categories.id, order_by=func.count(Likes.post_id).desc())
            .label("rn"),
        )
        .select_from(Categories)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == Categories.id,
        )
        .outerjoin(Genres, Categories.genre_id == Genres.id)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_day_ago,
            ),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .group_by(
            Categories.id,
            Categories.name,
            Genres.id,
            Genres.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .subquery("like_counts")
    )

    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.rn <= limit)
        .order_by(
            like_counts_subq.c.category_name,
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .all()
    )

    return result


def get_ranking_posts_categories_weekly(db: Session, limit: int = 50):
    """
    各カテゴリーでいいね数が多い投稿を取得 Weekly
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    top_categories_subq = (
        db.query(
            Categories.id.label("category_id"),
            func.count(Likes.post_id).label("total_likes"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_week_ago,
            ),
        )
        .group_by(Categories.id)
        .order_by(func.count(Likes.post_id).desc())
        .limit(10)
        .subquery("top_categories")
    )
    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Genres.id.label("genre_id"),
            Genres.name.label("genre_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
            func.row_number()
            .over(partition_by=Categories.id, order_by=func.count(Likes.post_id).desc())
            .label("rn"),
        )
        .select_from(Categories)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == Categories.id,
        )
        .outerjoin(Genres, Categories.genre_id == Genres.id)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_week_ago,
            ),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .group_by(
            Categories.id,
            Categories.name,
            Genres.id,
            Genres.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .subquery("like_counts")
    )

    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.rn <= limit)
        .order_by(
            like_counts_subq.c.category_name,
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .all()
    )

    return result


def get_ranking_posts_categories_monthly(db: Session, limit: int = 50):
    """
    各カテゴリーでいいね数が多い投稿を取得 Monthly
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )

    top_categories_subq = (
        db.query(
            Categories.id.label("category_id"),
            func.count(Likes.post_id).label("total_likes"),
        )
        .select_from(Categories)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_month_ago,
            ),
        )
        .group_by(Categories.id)
        .order_by(func.count(Likes.post_id).desc())
        .limit(10)
        .subquery("top_categories")
    )
    like_counts_subq = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Genres.id.label("genre_id"),
            Genres.name.label("genre_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Users.offical_flg.label("offical_flg"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),
            func.row_number()
            .over(partition_by=Categories.id, order_by=func.count(Likes.post_id).desc())
            .label("rn"),
        )
        .select_from(Categories)
        .join(
            top_categories_subq,
            top_categories_subq.c.category_id == Categories.id,
        )
        .outerjoin(Genres, Categories.genre_id == Genres.id)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(
            Posts,
            and_(
                Posts.id == PostCategories.post_id,
                active_post_cond,
            ),
        )
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            MediaAssets,
            and_(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            Likes,
            and_(
                Likes.post_id == Posts.id,
                Likes.created_at >= one_month_ago,
            ),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .group_by(
            Categories.id,
            Categories.name,
            Genres.id,
            Genres.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .subquery("like_counts")
    )

    result = (
        db.query(like_counts_subq)
        .filter(like_counts_subq.c.rn <= limit)
        .order_by(
            like_counts_subq.c.category_name,
            like_counts_subq.c.likes_count.desc().nullslast(),
        )
        .all()
    )

    return result


def get_ranking_posts_detail_overall_all_time(
    db: Session, page: int = 1, limit: int = 500
):
    """
    全期間でいいね数が多い投稿を取得
    """
    offset = (page - 1) * limit
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    rows = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .outerjoin(Users, Posts.creator_user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)  # 公開済みの投稿のみ
        .filter(Posts.deleted_at.is_(None))  # 削除されていない投稿のみ
        .filter(active_post_cond)
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .offset(offset)
        .limit(limit)
        .all()
    )
    post_ids = [row.Posts.id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row.Posts.is_time_sale = bool(post_sale_map.get(row.Posts.id, False))
    return rows


def get_ranking_posts_detail_overall_monthly(
    db: Session, page: int = 1, limit: int = 500
):
    """
    月間でいいね数が多い投稿を取得
    """
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    offset = (page - 1) * limit
    rows = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_month_ago)  # 過去30日以内のいいね
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .offset(offset)
        .limit(limit)
        .all()
    )
    post_ids = [row.Posts.id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row.Posts.is_time_sale = bool(post_sale_map.get(row.Posts.id, False))
    return rows


def get_ranking_posts_detail_overall_weekly(
    db: Session, page: int = 1, limit: int = 500
):
    """
    週間でいいね数が多い投稿を取得
    """
    one_week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    offset = (page - 1) * limit
    rows = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .outerjoin(Users, Posts.creator_user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.deleted_at.is_(None))
        .filter(active_post_cond)
        .filter(Posts.created_at >= one_week_ago)  # 過去7日以内のいいね
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .offset(offset)
        .limit(limit)
        .all()
    )

    post_ids = [row.Posts.id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row.Posts.is_time_sale = bool(post_sale_map.get(row.Posts.id, False))
    return rows


def get_ranking_posts_detail_overall_daily(
    db: Session, page: int = 1, limit: int = 500
):
    """
    日間でいいね数が多い投稿を取得
    """
    one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    offset = (page - 1) * limit
    rows = (
        db.query(
            Posts,
            func.count(Likes.post_id).label("likes_count"),
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .outerjoin(Users, Posts.creator_user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.THUMBNAIL),
        )
        .outerjoin(
            VideoAssets,
            (Posts.id == VideoAssets.post_id)
            & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.deleted_at.is_(None))
        .filter(active_post_cond)
        .filter(Posts.created_at >= one_day_ago)  # 過去1日以内のいいね
        .group_by(
            Posts.id,
            Users.profile_name,
            Users.offical_flg,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
            VideoAssets.duration_sec,
        )
        .order_by(desc("likes_count"))
        .offset(offset)
        .limit(limit)
        .all()
    )
    post_ids = [row.Posts.id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row.Posts.is_time_sale = bool(post_sale_map.get(row.Posts.id, False))
    return rows


def add_notification_for_post(
    db: Session,
    post: Posts = None,
    post_id: str = None,
    user_id: UUID = None,
    liked_user_id: UUID = None,
    type: str = "approved",
) -> None:
    """投稿に対する通知を追加

    Args:
        db: データベースセッション
        post_id: 投稿ID
        user_id: ユーザーID
        type: 通知タイプ "approved" | "rejected" | "like"
    """
    try:
        if type == "approved":
            try:
                should_send_notification_post_approval = True
                settings = (
                    db.query(UserSettings)
                    .filter(UserSettings.user_id == post.creator_user_id)
                    .first()
                )
                if (
                    settings is not None
                    and settings.settings
                    and isinstance(settings.settings, dict)
                ):
                    post_approve_setting = settings.settings.get("postApprove", True)
                    if post_approve_setting is False:
                        should_send_notification_post_approval = False
                if not should_send_notification_post_approval:
                    return

                profiles = (
                    db.query(Profiles)
                    .filter(Profiles.user_id == post.creator_user_id)
                    .first()
                )
                message = POST_APPROVED_MD.replace("-name-", profiles.username).replace(
                    "--post-url--",
                    f"{os.environ.get('FRONTEND_URL')}/post/detail?post_id={post.id}",
                )
                notification = Notifications(
                    user_id=post.creator_user_id,
                    type=NotificationType.USERS,
                    payload={
                        "type": "post",
                        "title": "投稿が承認されました",
                        "subtitle": "投稿が承認されました",
                        "message": message,
                        "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                        "redirect_url": f"/post/detail?post_id={post.id}",
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    is_read=False,
                    read_at=None,
                )
                db.add(notification)
                db.commit()
                payload_push_noti = {
                    "title": notification.payload["title"],
                    "body": notification.payload["subtitle"],
                    "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
                }
                push_notification_to_user(db, notification.user_id, payload_push_noti)
            except Exception as e:
                db.rollback()
                logger.error(f"Add notification for post approved error: {e}")
                pass
        elif type == "rejected":
            try:
                post = db.query(Posts).filter(Posts.id == post_id).first()
                profiles = (
                    db.query(Profiles)
                    .filter(Profiles.user_id == post.creator_user_id)
                    .first()
                )
                should_send_notification_post_approval = True
                settings = (
                    db.query(UserSettings)
                    .filter(UserSettings.user_id == post.creator_user_id)
                    .first()
                )
                if (
                    settings is not None
                    and settings.settings
                    and isinstance(settings.settings, dict)
                ):
                    post_approve_setting = settings.settings.get("postApprove", True)
                    if post_approve_setting is False:
                        should_send_notification_post_approval = False
                if not should_send_notification_post_approval:
                    return
                message = POST_REJECTED_MD.replace("-name-", profiles.username).replace(
                    "--post-url--",
                    f"{os.environ.get('FRONTEND_URL')}/account/post/{post.id}",
                )
                notification = Notifications(
                    user_id=post.creator_user_id,
                    type=NotificationType.USERS,
                    payload={
                        "type": "post",
                        "title": "投稿が拒否されました",
                        "subtitle": "投稿が拒否されました",
                        "message": message,
                        "avatar": "https://logo.mijfans.jp/bimi/logo.svg",
                        "redirect_url": f"/account/post/{post.id}",
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    is_read=False,
                    read_at=None,
                )
                db.add(notification)
                db.commit()
                payload_push_noti = {
                    "title": notification.payload["title"],
                    "body": notification.payload["subtitle"],
                    "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
                }
                push_notification_to_user(db, notification.user_id, payload_push_noti)
            except Exception as e:
                db.rollback()
                logger.error(f"Add notification for post rejected error: {e}")
                pass
        elif type == "like":
            should_send_notification_post_like = True
            settings = (
                db.query(UserSettings)
                .filter(UserSettings.user_id == post.creator_user_id)
                .first()
            )
            if (
                settings is not None
                and settings.settings
                and isinstance(settings.settings, dict)
            ):
                post_like_setting = settings.settings.get("postLike", True)
                if post_like_setting is False:
                    should_send_notification_post_like = False
            if not should_send_notification_post_like:
                return

            liked_user_profile = (
                db.query(Profiles).filter(Profiles.user_id == liked_user_id).first()
            )
            if not liked_user_profile:
                raise Exception("Liked user profile not found")
            try:
                notification = Notifications(
                    user_id=post.creator_user_id,
                    type=NotificationType.USERS,
                    payload={
                        "title": f"{liked_user_profile.username} が投稿にいいねしました",
                        "subtitle": f"{liked_user_profile.username} が投稿にいいねしました",
                        "avatar": f"{os.environ.get('CDN_BASE_URL')}/{liked_user_profile.avatar_url}",
                        "redirect_url": f"/profile?username={liked_user_profile.username}",
                    },
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                    is_read=False,
                    read_at=None,
                )
                db.add(notification)
                db.commit()
                payload_push_noti = {
                    "title": notification.payload["title"],
                    "body": notification.payload["subtitle"],
                    "url": f"{os.getenv('FRONTEND_URL', 'https://mijfans.jp/')}/notifications",
                }
                push_notification_to_user(db, notification.user_id, payload_push_noti)
            except Exception as e:
                db.rollback()
                logger.error(f"Add notification for post like error: {e}")
    except Exception as e:
        logger.error(f"Add notification for post error: {e}")
        pass


# ========== OGP画像取得 ==========
def get_post_ogp_image_url(db: Session, post_id: str) -> str | None:
    """
    投稿のOGP画像URLを取得
    優先順位: kind=1のメディアアセット → クリエイターのカバー画像 → デフォルト画像
    """

    # 投稿を取得
    post = db.query(Posts).filter(Posts.id == post_id).first()
    if not post:
        raise Exception("Post not found")

    # kind=1のメディアアセットを取得
    media_asset = (
        db.query(MediaAssets)
        .filter(
            and_(
                MediaAssets.post_id == post_id,
                MediaAssets.kind == MediaAssetKind.OGP,
            )
        )
        .first()
    )

    if not media_asset:
        return None

    return f"{CDN_BASE_URL}/{media_asset.storage_key}"


def add_mail_notification_for_post(
    db: Session, post_id: UUID = None, type: str = "approved"
) -> None:
    """投稿に対するメール通知を追加

    Args:
        db: データベースセッション
        user_id: ユーザーID
        type: 通知タイプ "approved" | "rejected"
    """
    try:
        result = (
            db.query(
                Users,
                Profiles,
                Posts,
                UserSettings.settings,
            )
            .join(Profiles, Users.id == Profiles.user_id)
            .join(Posts, Users.id == Posts.creator_user_id)
            .outerjoin(
                UserSettings,
                and_(
                    Users.id == UserSettings.user_id,
                    UserSettings.type == UserSettingsType.EMAIL,
                ),
            )
            .filter(Posts.id == post_id)
            .first()
        )

        if not result:
            raise Exception("Can not query user settings")

        # タプルをアンパック
        user, profile, post, settings = result

        # メール通知の設定をチェック
        # settingsがNoneの場合、またはpostApproveがTrue/Noneの場合は送信
        should_send = True
        if settings is not None and isinstance(settings, dict):
            post_approve_setting = settings.get("postApprove", True)
            if post_approve_setting is False:
                should_send = False

        if not should_send:
            return

        if type == "approved":
            send_post_approval_email(
                user.email,
                profile.username if profile else user.profile_name,
                str(post.id),
            )
        elif type == "rejected":
            send_post_rejection_email(
                user.email,
                profile.username if profile else user.profile_name,
                post.reject_comments,
                str(post.id),
            )
    except Exception as e:
        logger.exception(f"{e}")
        logger.error(f"Add mail notification for post error: {e}")
        pass


def get_post_ogp_data(db: Session, post_id: str) -> Dict[str, Any] | None:
    """
    投稿のOGP生成に必要な全ての情報を取得

    Args:
        db: データベースセッション
        post_id: 投稿ID

    Returns:
        Dict[str, Any]: OGP情報（投稿詳細 + クリエイター情報 + OGP画像）
        None: 投稿が見つからない場合
    """
    from app.models.generation_media import GenerationMedia
    from app.constants.enums import GenerationMediaKind

    # 投稿情報 + クリエイター情報 + プロフィール情報を一度に取得
    result = (
        db.query(
            Posts.id,
            Posts.description,
            Posts.post_type,
            Posts.created_at,
            Users.id.label("creator_user_id"),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label("ogp_image_url"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            MediaAssets,
            (Posts.id == MediaAssets.post_id)
            & (MediaAssets.kind == MediaAssetKind.OGP),
        )
        .filter(Posts.id == post_id)
        .filter(Posts.deleted_at.is_(None))
        .first()
    )

    if not result:
        return None

    # OGP画像URLを取得
    # 優先順位: generation_media (kind=2) → thumbnail → デフォルト画像
    ogp_image_url = None
    if result.ogp_image_url:
        ogp_image_url = f"{CDN_BASE_URL}/{result.ogp_image_url}"
    else:
        # 1. generation_mediaからOGP画像を取得
        generation_media = (
            db.query(GenerationMedia)
            .filter(
                GenerationMedia.post_id == post_id,
                GenerationMedia.kind == GenerationMediaKind.POST_IMAGE,
            )
            .first()
        )
        if generation_media:
            ogp_image_url = f"{CDN_BASE_URL}/{generation_media.storage_key}"
        else:
            ogp_image_url = "https://logo.mijfans.jp/bimi/ogp-image.png"

    if ogp_image_url is None:
        ogp_image_url = "https://logo.mijfans.jp/bimi/ogp-image.png"

    # タイトル生成（descriptionの最初の30文字）
    description = result.description or ""
    title = description[:30] + "..." if len(description) > 30 else description

    # アバターURL
    avatar_url = None
    if result.avatar_url:
        avatar_url = f"{CDN_BASE_URL}/{result.avatar_url}"

    return {
        "post_id": str(result.id),
        "title": title,
        "description": description,
        "post_type": result.post_type,
        "ogp_image_url": ogp_image_url,
        "creator": {
            "user_id": str(result.creator_user_id),
            "profile_name": result.profile_name or "クリエイター",
            "username": result.username or "",
            "avatar_url": avatar_url,
        },
        "created_at": result.created_at,
    }


def mark_post_as_deleted(db: Session, post_id: str, user_id: str):
    """
    投稿を削除マーク
    """
    post = db.query(Posts).filter(Posts.id == post_id).first()
    if not post:
        raise Exception("Post not found")
    if post.creator_user_id != user_id:
        raise Exception("User is not the creator of the post")
    post.status = PostStatus.DELETED
    post.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return True


def get_post_ranking_overall(
    db: Session, limit: int = 20, period: str = "all_time", page: int = 1
):
    """
    Phase1: best post per creator (unique creators)
    Phase2: remaining posts by old logic (exclude post_ids from phase1)
    Pagination applies to the combined list: [phase1 ...] + [phase2 ...]
    """

    # ---------- pagination
    if page < 1:
        page = 1
    if limit < 1:
        limit = 20
    offset = (page - 1) * limit

    # ---------- time + active post
    now_sql = func.now()
    now = datetime.now(timezone.utc)
    active_post_cond = sa_and(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        sa_or(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now_sql),
        sa_or(Posts.expiration_at.is_(None), Posts.expiration_at > now_sql),
    )

    PAYMENT_SUCCEEDED = PaymentStatus.SUCCEEDED
    ORDER_TYPE_PLAN = PaymentType.PLAN
    ORDER_TYPE_PRICE = PaymentType.SINGLE
    MIN_PAYMENT_PRICE = 500

    # ---------- period rolling window (UTC naive)
    start_dt = None
    if period == "daily":
        start_dt = now - timedelta(days=1)
    elif period == "weekly":
        start_dt = now - timedelta(days=7)
    elif period == "monthly":
        start_dt = now - timedelta(days=30)
    # all_time => None

    # ---------- base payment condition (for counting)
    base_payment_cond = sa_and(
        Payments.status == PAYMENT_SUCCEEDED,
        Payments.payment_price >= MIN_PAYMENT_PRICE,
        Payments.paid_at.isnot(None),
    )
    if start_dt is not None:
        base_payment_cond = sa_and(base_payment_cond, Payments.paid_at >= start_dt)

    # ---------- purchase_count per post (price)
    price_purchase_sq = (
        db.query(
            Prices.post_id.label("post_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PRICE,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == Prices.id,
                base_payment_cond,
            ),
        )
        .group_by(Prices.post_id)
        .subquery()
    )

    # ---------- purchase_count per post (plan)
    plan_purchase_sq = (
        db.query(
            PostPlans.post_id.label("post_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PLAN,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == PostPlans.plan_id,
                base_payment_cond,
            ),
        )
        .group_by(PostPlans.post_id)
        .subquery()
    )

    # ---------- merge purchases
    union_sq = (
        db.query(
            price_purchase_sq.c.post_id.label("post_id"),
            price_purchase_sq.c.purchase_count.label("purchase_count"),
        )
        .union_all(
            db.query(
                plan_purchase_sq.c.post_id.label("post_id"),
                plan_purchase_sq.c.purchase_count.label("purchase_count"),
            )
        )
        .subquery()
    )

    purchase_merged_sq = (
        db.query(
            union_sq.c.post_id.label("post_id"),
            func.sum(union_sq.c.purchase_count).label("purchase_count"),
        )
        .group_by(union_sq.c.post_id)
        .subquery()
    )

    # ---------- bookmark_count per post (within period if specified)
    bookmark_q = db.query(
        Bookmarks.post_id.label("post_id"),
        func.count(func.distinct(Bookmarks.user_id)).label("bookmark_count"),
    )
    if start_dt is not None:
        bookmark_q = bookmark_q.filter(Bookmarks.created_at >= start_dt)
    bookmark_sq = bookmark_q.group_by(Bookmarks.post_id).subquery()

    # ---------- activity OR filter (only for daily/weekly/monthly)
    payment_activity_sq = None
    bookmark_activity_sq = None
    period_or_cond = None

    if start_dt is not None:
        price_paid_posts_sq = db.query(Prices.post_id.label("post_id")).join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PRICE,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == Prices.id,
                Payments.status == PAYMENT_SUCCEEDED,
                Payments.paid_at.isnot(None),
                Payments.paid_at >= start_dt,
                Payments.payment_price >= MIN_PAYMENT_PRICE,
            ),
        )
        plan_paid_posts_sq = db.query(PostPlans.post_id.label("post_id")).join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PLAN,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == PostPlans.plan_id,
                Payments.status == PAYMENT_SUCCEEDED,
                Payments.paid_at.isnot(None),
                Payments.paid_at >= start_dt,
                Payments.payment_price >= MIN_PAYMENT_PRICE,
            ),
        )
        payment_activity_sq = price_paid_posts_sq.union(plan_paid_posts_sq).subquery()

        bookmark_activity_sq = (
            db.query(Bookmarks.post_id.label("post_id"))
            .filter(Bookmarks.created_at >= start_dt)
            .subquery()
        )

        period_or_cond = sa_or(
            payment_activity_sq.c.post_id.isnot(None),
            bookmark_activity_sq.c.post_id.isnot(None),
            Posts.created_at >= start_dt,
        )

    # ---------- base dataset: 1 row / post
    base_q = (
        db.query(
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Posts.created_at.label("created_at"),
            func.coalesce(purchase_merged_sq.c.purchase_count, 0).label(
                "purchase_count"
            ),
            func.coalesce(bookmark_sq.c.bookmark_count, 0).label("bookmark_count"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
        )
        .select_from(Posts)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(purchase_merged_sq, purchase_merged_sq.c.post_id == Posts.id)
        .outerjoin(bookmark_sq, bookmark_sq.c.post_id == Posts.id)
        .outerjoin(
            MediaAssets,
            sa_and(
                Posts.id == MediaAssets.post_id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            VideoAssets,
            sa_and(
                Posts.id == VideoAssets.post_id,
                VideoAssets.kind == MediaAssetKind.MAIN_VIDEO,
            ),
        )
        .filter(active_post_cond)
    )

    if period_or_cond is not None:
        base_q = (
            base_q.outerjoin(
                payment_activity_sq, payment_activity_sq.c.post_id == Posts.id
            )
            .outerjoin(bookmark_activity_sq, bookmark_activity_sq.c.post_id == Posts.id)
            .filter(period_or_cond)
        )

    base_sq = base_q.group_by(
        Posts.id,
        Posts.creator_user_id,
        Posts.created_at,
        Users.profile_name,
        Users.offical_flg,
        Profiles.username,
        Profiles.avatar_url,
        MediaAssets.storage_key,
        VideoAssets.duration_sec,
        purchase_merged_sq.c.purchase_count,
        bookmark_sq.c.bookmark_count,
    ).subquery("base_sq")

    # ---------- phase1: best post / creator
    creator_rank_sq = db.query(
        base_sq,
        func.row_number()
        .over(
            partition_by=base_sq.c.creator_user_id,
            order_by=(
                base_sq.c.purchase_count.desc(),
                base_sq.c.bookmark_count.desc(),
                base_sq.c.created_at.desc(),
                base_sq.c.post_id.desc(),  # tie-break for stable paging
            ),
        )
        .label("rn_creator"),
    ).subquery("creator_rank_sq")

    phase1_sq = (
        db.query(creator_rank_sq)
        .filter(creator_rank_sq.c.rn_creator == 1)
        .subquery("phase1_sq")
    )

    phase1_total = db.query(func.count()).select_from(phase1_sq).scalar() or 0

    # ---------- phase2: all posts excluding phase1 post_ids (no duplicate post_id)
    phase2_sq = (
        db.query(base_sq)
        .filter(~base_sq.c.post_id.in_(db.query(phase1_sq.c.post_id)))
        .subquery("phase2_sq")
    )

    rows = []

    # ========== pagination across combined list ==========
    if offset < phase1_total:
        take1 = min(limit, phase1_total - offset)

        part1 = (
            db.query(
                Posts,
                phase1_sq.c.purchase_count.label("purchase_count"),
                phase1_sq.c.bookmark_count.label("bookmark_count"),
                phase1_sq.c.profile_name,
                phase1_sq.c.offical_flg,
                phase1_sq.c.username,
                phase1_sq.c.avatar_url,
                phase1_sq.c.thumbnail_key,
                phase1_sq.c.duration_sec,
            )
            .join(phase1_sq, phase1_sq.c.post_id == Posts.id)
            .order_by(
                phase1_sq.c.purchase_count.desc(),
                phase1_sq.c.bookmark_count.desc(),
                phase1_sq.c.created_at.desc(),
                phase1_sq.c.post_id.desc(),
            )
            .offset(offset)
            .limit(take1)
            .all()
        )
        rows.extend(part1)

        take2 = limit - take1
        if take2 > 0:
            part2 = (
                db.query(
                    Posts,
                    phase2_sq.c.purchase_count.label("purchase_count"),
                    phase2_sq.c.bookmark_count.label("bookmark_count"),
                    phase2_sq.c.profile_name,
                    phase2_sq.c.offical_flg,
                    phase2_sq.c.username,
                    phase2_sq.c.avatar_url,
                    phase2_sq.c.thumbnail_key,
                    phase2_sq.c.duration_sec,
                )
                .join(phase2_sq, phase2_sq.c.post_id == Posts.id)
                .order_by(
                    phase2_sq.c.purchase_count.desc(),
                    phase2_sq.c.bookmark_count.desc(),
                    phase2_sq.c.created_at.desc(),
                    phase2_sq.c.post_id.desc(),
                )
                .offset(0)
                .limit(take2)
                .all()
            )
            rows.extend(part2)
    else:
        phase2_offset = offset - phase1_total

        rows = (
            db.query(
                Posts,
                phase2_sq.c.purchase_count.label("purchase_count"),
                phase2_sq.c.bookmark_count.label("bookmark_count"),
                phase2_sq.c.profile_name,
                phase2_sq.c.offical_flg,
                phase2_sq.c.username,
                phase2_sq.c.avatar_url,
                phase2_sq.c.thumbnail_key,
                phase2_sq.c.duration_sec,
            )
            .join(phase2_sq, phase2_sq.c.post_id == Posts.id)
            .order_by(
                phase2_sq.c.purchase_count.desc(),
                phase2_sq.c.bookmark_count.desc(),
                phase2_sq.c.created_at.desc(),
                phase2_sq.c.post_id.desc(),
            )
            .offset(phase2_offset)
            .limit(limit)
            .all()
        )

    # ---------- time sale flag
    post_ids = [row[0].id for row in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    for row in rows:
        row[0].is_time_sale = bool(post_sale_map.get(row[0].id, False))

    return rows


def _build_category_base_sq(db: Session, period: str = "all_time"):
    """
    Return:
      - base_sq: 1 row per (category_id, post_id) with score columns
      - active_post_cond
      - start_dt
      - payment_activity_sq, bookmark_activity_sq, period_or_cond (for OR activity filter)
    """
    now_sql = func.now()
    now = datetime.now(timezone.utc)
    active_post_cond = sa_and(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        sa_or(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now_sql),
        sa_or(Posts.expiration_at.is_(None), Posts.expiration_at > now_sql),
    )

    PAYMENT_SUCCEEDED = PaymentStatus.SUCCEEDED
    ORDER_TYPE_PLAN = PaymentType.PLAN
    ORDER_TYPE_PRICE = PaymentType.SINGLE
    MIN_PAYMENT_PRICE = 500

    # rolling window (UTC naive)
    start_dt = None
    if period == "daily":
        start_dt = now - timedelta(days=1)
    elif period == "weekly":
        start_dt = now - timedelta(days=7)
    elif period == "monthly":
        start_dt = now - timedelta(days=30)

    # payment cond for counting
    base_payment_cond = sa_and(
        Payments.status == PAYMENT_SUCCEEDED,
        Payments.payment_price >= MIN_PAYMENT_PRICE,
        Payments.paid_at.isnot(None),
    )
    if start_dt is not None:
        base_payment_cond = sa_and(base_payment_cond, Payments.paid_at >= start_dt)

    # purchase_count per post (price)
    price_purchase_sq = (
        db.query(
            Prices.post_id.label("post_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PRICE,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == Prices.id,
                base_payment_cond,
            ),
        )
        .group_by(Prices.post_id)
        .subquery()
    )

    # purchase_count per post (plan)
    plan_purchase_sq = (
        db.query(
            PostPlans.post_id.label("post_id"),
            func.count(func.distinct(Payments.id)).label("purchase_count"),
        )
        .join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PLAN,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == PostPlans.plan_id,
                base_payment_cond,
            ),
        )
        .group_by(PostPlans.post_id)
        .subquery()
    )

    # merge purchases
    union_sq = (
        db.query(
            price_purchase_sq.c.post_id.label("post_id"),
            price_purchase_sq.c.purchase_count.label("purchase_count"),
        )
        .union_all(
            db.query(
                plan_purchase_sq.c.post_id.label("post_id"),
                plan_purchase_sq.c.purchase_count.label("purchase_count"),
            )
        )
        .subquery()
    )

    purchase_merged_sq = (
        db.query(
            union_sq.c.post_id.label("post_id"),
            func.sum(union_sq.c.purchase_count).label("purchase_count"),
        )
        .group_by(union_sq.c.post_id)
        .subquery()
    )

    # bookmark_count per post (within period if specified)
    bookmark_q = db.query(
        Bookmarks.post_id.label("post_id"),
        func.count(func.distinct(Bookmarks.user_id)).label("bookmark_count"),
    )
    if start_dt is not None:
        bookmark_q = bookmark_q.filter(Bookmarks.created_at >= start_dt)
    bookmark_sq = bookmark_q.group_by(Bookmarks.post_id).subquery()

    # activity OR filter
    payment_activity_sq = None
    bookmark_activity_sq = None
    period_or_cond = None

    if start_dt is not None:
        price_paid_posts = db.query(Prices.post_id.label("post_id")).join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PRICE,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == Prices.id,
                Payments.status == PAYMENT_SUCCEEDED,
                Payments.paid_at.isnot(None),
                Payments.paid_at >= start_dt,
                Payments.payment_price >= MIN_PAYMENT_PRICE,
            ),
        )
        plan_paid_posts = db.query(PostPlans.post_id.label("post_id")).join(
            Payments,
            sa_and(
                Payments.order_type == ORDER_TYPE_PLAN,
                cast(Payments.order_id, PG_UUID(as_uuid=True)) == PostPlans.plan_id,
                Payments.status == PAYMENT_SUCCEEDED,
                Payments.paid_at.isnot(None),
                Payments.paid_at >= start_dt,
                Payments.payment_price >= MIN_PAYMENT_PRICE,
            ),
        )
        payment_activity_sq = price_paid_posts.union(plan_paid_posts).subquery()

        bookmark_activity_sq = (
            db.query(Bookmarks.post_id.label("post_id"))
            .filter(Bookmarks.created_at >= start_dt)
            .subquery()
        )

        period_or_cond = sa_or(
            payment_activity_sq.c.post_id.isnot(None),
            bookmark_activity_sq.c.post_id.isnot(None),
            Posts.created_at >= start_dt,
        )

    # base dataset: 1 row per (category, post)
    base_q = (
        db.query(
            Categories.id.label("category_id"),
            Categories.name.label("category_name"),
            Genres.id.label("genre_id"),
            Genres.name.label("genre_name"),
            Posts.id.label("post_id"),
            Posts.creator_user_id.label("creator_user_id"),
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Users.offical_flg.label("offical_flg"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.coalesce(purchase_merged_sq.c.purchase_count, 0).label(
                "purchase_count"
            ),
            func.coalesce(bookmark_sq.c.bookmark_count, 0).label("bookmark_count"),
            Posts.created_at.label("created_at"),
        )
        .select_from(Categories)
        .outerjoin(Genres, Categories.genre_id == Genres.id)
        .outerjoin(PostCategories, PostCategories.category_id == Categories.id)
        .outerjoin(Posts, sa_and(Posts.id == PostCategories.post_id, active_post_cond))
        .outerjoin(Users, Users.id == Posts.creator_user_id)
        .outerjoin(Profiles, Profiles.user_id == Users.id)
        .outerjoin(
            MediaAssets,
            sa_and(
                MediaAssets.post_id == Posts.id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
            ),
        )
        .outerjoin(
            VideoAssets,
            sa_and(
                VideoAssets.post_id == Posts.id,
                VideoAssets.kind == MediaAssetKind.MAIN_VIDEO,
            ),
        )
        .outerjoin(purchase_merged_sq, purchase_merged_sq.c.post_id == Posts.id)
        .outerjoin(bookmark_sq, bookmark_sq.c.post_id == Posts.id)
    )

    base_q = base_q.filter(Posts.id.isnot(None))

    if period_or_cond is not None:
        base_q = (
            base_q.outerjoin(
                payment_activity_sq, payment_activity_sq.c.post_id == Posts.id
            )
            .outerjoin(bookmark_activity_sq, bookmark_activity_sq.c.post_id == Posts.id)
            .filter(period_or_cond)
        )

    base_sq = base_q.group_by(
        Categories.id,
        Categories.name,
        Genres.id,
        Genres.name,
        Posts.id,
        Posts.creator_user_id,
        Posts.post_type,
        Posts.description,
        Posts.created_at,
        Users.profile_name,
        Users.offical_flg,
        Profiles.username,
        Profiles.avatar_url,
        MediaAssets.storage_key,
        VideoAssets.duration_sec,
        purchase_merged_sq.c.purchase_count,
        bookmark_sq.c.bookmark_count,
    ).subquery("base_sq")

    return base_sq


def get_ranking_posts_categories_overall(
    db: Session,
    limit_per_category: int = 6,
    period: str = "all_time",
    top_n_categories: int = 10,
):
    base_sq = _build_category_base_sq(db, period=period)

    eligible_categories_sq = (
        db.query(
            base_sq.c.category_id.label("category_id"),
            func.count(func.distinct(base_sq.c.creator_user_id)).label("creator_count"),
        )
        .group_by(base_sq.c.category_id)
        .having(func.count(func.distinct(base_sq.c.creator_user_id)) >= 2)
        .subquery("eligible_categories")
    )

    top_categories_sq = (
        db.query(
            base_sq.c.category_id.label("category_id"),
            func.coalesce(func.sum(base_sq.c.purchase_count), 0).label(
                "total_purchases"
            ),
        )
        .join(
            eligible_categories_sq,
            eligible_categories_sq.c.category_id == base_sq.c.category_id,
        )
        .group_by(base_sq.c.category_id)
        .order_by(desc("total_purchases"))
        .limit(top_n_categories)
        .subquery("top_categories")
    )

    creator_rank_sq = (
        db.query(
            base_sq,
            func.row_number()
            .over(
                partition_by=(base_sq.c.category_id, base_sq.c.creator_user_id),
                order_by=(
                    base_sq.c.purchase_count.desc(),
                    base_sq.c.bookmark_count.desc(),
                    base_sq.c.created_at.desc(),
                    base_sq.c.post_id.desc(),
                ),
            )
            .label("rn_creator"),
        )
        .join(
            top_categories_sq, top_categories_sq.c.category_id == base_sq.c.category_id
        )
        .subquery("creator_rank_sq")
    )

    creator_dedup_sq = (
        db.query(creator_rank_sq)
        .filter(creator_rank_sq.c.rn_creator == 1)
        .subquery("creator_dedup_sq")
    )

    final_rank_sq = db.query(
        creator_dedup_sq,
        func.row_number()
        .over(
            partition_by=creator_dedup_sq.c.category_id,
            order_by=(
                creator_dedup_sq.c.purchase_count.desc(),
                creator_dedup_sq.c.bookmark_count.desc(),
                creator_dedup_sq.c.created_at.desc(),
                creator_dedup_sq.c.post_id.desc(),
            ),
        )
        .label("rn"),
    ).subquery("final_rank_sq")

    result = (
        db.query(final_rank_sq)
        .filter(final_rank_sq.c.rn <= limit_per_category)
        .order_by(final_rank_sq.c.category_name, final_rank_sq.c.rn.asc())
        .all()
    )
    return result


def get_ranking_posts_detail_overall(
    db: Session, page: int = 1, limit: int = 20, period: str = "all_time"
):
    return get_post_ranking_overall(db, limit, period, page)


def get_ranking_posts_detail_categories(
    db: Session,
    category: str,
    page: int = 1,
    limit: int = 20,
    period: str = "all_time",
):
    base_sq = _build_category_base_sq(db, period=period)

    offset = (page - 1) * limit
    if offset < 0:
        offset = 0

    # scope to 1 category
    cat_sq = (
        db.query(base_sq).filter(base_sq.c.category_id == category).subquery("cat_sq")
    )

    # phase1: best post per creator in this category
    creator_rank_sq = db.query(
        cat_sq,
        func.row_number()
        .over(
            partition_by=cat_sq.c.creator_user_id,
            order_by=(
                cat_sq.c.purchase_count.desc(),
                cat_sq.c.bookmark_count.desc(),
                cat_sq.c.created_at.desc(),
                cat_sq.c.post_id.desc(),
            ),
        )
        .label("rn_creator"),
    ).subquery("creator_rank_sq")

    phase1_sq = (
        db.query(creator_rank_sq)
        .filter(creator_rank_sq.c.rn_creator == 1)
        .subquery("phase1_sq")
    )

    phase1_total = db.query(func.count()).select_from(phase1_sq).scalar() or 0

    # phase2: all remaining posts (exclude phase1 post_ids)
    phase2_sq = (
        db.query(cat_sq)
        .filter(~cat_sq.c.post_id.in_(db.query(phase1_sq.c.post_id)))
        .subquery("phase2_sq")
    )

    rows = []

    if offset < phase1_total:
        take1 = min(limit, phase1_total - offset)

        part1 = (
            db.query(phase1_sq)
            .order_by(
                phase1_sq.c.purchase_count.desc(),
                phase1_sq.c.bookmark_count.desc(),
                phase1_sq.c.created_at.desc(),
                phase1_sq.c.post_id.desc(),
            )
            .offset(offset)
            .limit(take1)
            .all()
        )
        rows.extend(part1)

        take2 = limit - take1
        if take2 > 0:
            part2 = (
                db.query(phase2_sq)
                .order_by(
                    phase2_sq.c.purchase_count.desc(),
                    phase2_sq.c.bookmark_count.desc(),
                    phase2_sq.c.created_at.desc(),
                    phase2_sq.c.post_id.desc(),
                )
                .offset(0)
                .limit(take2)
                .all()
            )
            rows.extend(part2)
    else:
        phase2_offset = offset - phase1_total
        rows = (
            db.query(phase2_sq)
            .order_by(
                phase2_sq.c.purchase_count.desc(),
                phase2_sq.c.bookmark_count.desc(),
                phase2_sq.c.created_at.desc(),
                phase2_sq.c.post_id.desc(),
            )
            .offset(phase2_offset)
            .limit(limit)
            .all()
        )

    post_ids = [r.post_id for r in rows]
    post_sale_map = get_post_sale_flag_map(db, post_ids)
    return rows, post_sale_map
