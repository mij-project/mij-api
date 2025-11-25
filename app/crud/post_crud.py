from operator import or_
import os
import re
from fastapi import HTTPException
from sqlalchemy.orm import Session, aliased
from sqlalchemy import distinct, distinct, distinct, func, desc, exists, and_
from app.models import UserSettings
from app.models.genres import Genres
from app.models.notifications import Notifications
from app.models.posts import Posts
from app.models.social import Follows, Follows, Follows, Likes, Bookmarks, Comments
from uuid import UUID
from datetime import datetime, timezone
from app.constants.enums import AccountType, AccountType, AccountType, PostStatus, MediaAssetKind, MediaAssetStatus
from app.schemas.notification import NotificationType
from app.schemas.post import PostCreateRequest
from app.models.post_categories import PostCategories
from app.models.categories import Categories
from typing import List, Dict, Any
from app.models.user import Users
from app.models.profiles import Profiles
from app.models.post_categories import PostCategories
from app.models.media_assets import MediaAssets
from app.models.plans import Plans, PostPlans   
from app.models.prices import Prices
from app.models.media_renditions import MediaRenditions
from app.crud.entitlements_crud import check_entitlement
from app.api.commons.utils import get_video_duration
from app.constants.enums import PlanStatus
from app.models.purchases import Purchases
from app.models.orders import Orders, OrderItems
from app.models.media_rendition_jobs import MediaRenditionJobs
from app.constants.enums import PostType
from datetime import datetime, timedelta
from app.schemas.user_settings import UserSettingsType
from app.services.email.send_email import send_post_approval_email, send_post_rejection_email
from app.services.s3.presign import presign_get
from app.constants.enums import MediaAssetKind, MediaAssetStatus
from app.core.logger import Logger  
logger = Logger.get_logger()
# エイリアスを定義
ThumbnailAssets = aliased(MediaAssets)
VideoAssets = aliased(MediaAssets)
# ========== 投稿管理 ==========

MEDIA_CDN_URL = os.getenv("MEDIA_CDN_URL")
CDN_BASE_URL = os.getenv("CDN_BASE_URL")

POST_APPROVED_MD = """## Mijfans 投稿の審査が完了しました

-name- 様

投稿の審査が完了いたしました。

> ✅ **審査結果: 承認**  
> おめでとうございます！投稿が承認されました。

[投稿を確認する](--post-url--)

すぐに公開しましょう。  
ご不明な点がございましたら、サポートまでお問い合わせください。
"""

POST_REJECTED_MD = """## Mijfans 投稿の審査が完了しました

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
    peding_posts_count = db.query(Posts).filter(Posts.creator_user_id == user_id).filter(Posts.deleted_at.is_(None)).filter(Posts.status == PostStatus.PENDING).count()

    # 修正
    rejected_posts_count = db.query(Posts).filter(Posts.creator_user_id == user_id).filter(Posts.deleted_at.is_(None)).filter(Posts.status == PostStatus.REJECTED).count()

    # 非公開
    unpublished_posts_count = db.query(Posts).filter(Posts.creator_user_id == user_id).filter(Posts.deleted_at.is_(None)).filter(Posts.status == PostStatus.UNPUBLISHED).count()

    # 削除
    deleted_posts_count = db.query(Posts).filter(Posts.creator_user_id == user_id).filter(Posts.deleted_at.is_(None)).filter(Posts.status == PostStatus.DELETED).count()

    # 公開
    approved_posts_count = db.query(Posts).filter(Posts.creator_user_id == user_id).filter(Posts.deleted_at.is_(None)).filter(Posts.status == PostStatus.APPROVED).count()

    return {
        "peding_posts_count": peding_posts_count,
        "rejected_posts_count": rejected_posts_count,
        "unpublished_posts_count": unpublished_posts_count,
        "deleted_posts_count": deleted_posts_count,
        "approved_posts_count": approved_posts_count
    }

def get_posts_by_category_slug(db: Session, slug: str, page: int = 1, per_page: int = 100) -> List[Posts]:
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
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
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

    return result, total

def _build_post_status_query(db: Session, user_id: UUID, post_statuses: List[PostStatus]):
    """
    投稿ステータス取得クエリの共通部分
    """
    VideoAsset = aliased(MediaAssets)

    return (
        db.query(
            Posts,
            func.count(func.distinct(Likes.user_id)).label('likes_count'),
            func.count(func.distinct(Comments.id)).label('comments_count'),
            func.count(func.distinct(OrderItems.id)).label('purchase_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label('post_price'),
            func.min(Prices.currency).label('post_currency'),
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAsset.duration_sec
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAsset, (Posts.id == VideoAsset.post_id) & (VideoAsset.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .outerjoin(OrderItems, Posts.id == OrderItems.post_id)
        .outerjoin(Prices, Posts.id == Prices.post_id)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status.in_(post_statuses))
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAsset.duration_sec)
        .order_by(desc(Posts.created_at))
    )

def get_post_status_by_user_id(db: Session, user_id: UUID) -> dict:
    """
    ユーザーの投稿ステータスを取得
    """

    # 審査中の投稿を取得
    pending_posts = _build_post_status_query(db, user_id, [PostStatus.PENDING, PostStatus.RESUBMIT, PostStatus.CONVERTING]).all()

    # 拒否された投稿を取得
    rejected_posts = _build_post_status_query(db, user_id, [PostStatus.REJECTED]).all()

    # 非公開の投稿を取得
    unpublished_posts = _build_post_status_query(db, user_id, [PostStatus.UNPUBLISHED]).all()

    # 削除された投稿を取得
    deleted_posts = _build_post_status_query(db, user_id, [PostStatus.DELETED]).all()

    # 公開された投稿を取得
    approved_posts = _build_post_status_query(db, user_id, [PostStatus.APPROVED]).all()

    return {
        "pending_posts": pending_posts,
        "rejected_posts": rejected_posts,
        "unpublished_posts": unpublished_posts,
        "deleted_posts": deleted_posts,
        "approved_posts": approved_posts
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
        **media_info
    }

def get_posts_by_plan_id(db: Session, plan_id: UUID, user_id: UUID) -> List[tuple]:
    """
    プランに紐づく投稿一覧を取得
    ユーザーがそのプランを購入しているか確認してから返す
    """

    ThumbnailAssets = aliased(MediaAssets)

    # ユーザーがこのプランを購入しているか確認
    purchase = (
        db.query(Purchases)
        .filter(
            Purchases.user_id == user_id,
            Purchases.plan_id == plan_id,
            Purchases.deleted_at.is_(None)
        )
        .first()
    )

    if not purchase:
        return []

    # プランに紐づく投稿を取得
    return (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label('thumbnail_key'),
            ThumbnailAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label('likes_count'),
            func.count(func.distinct(Comments.id)).label('comments_count'),
            Posts.created_at
        )
        .join(PostPlans, Posts.id == PostPlans.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(ThumbnailAssets, (Posts.id == ThumbnailAssets.post_id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .filter(
            PostPlans.plan_id == plan_id,
            Posts.deleted_at.is_(None),
            Posts.status == PostStatus.APPROVED
        )
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
            Posts.created_at
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

def get_liked_posts_by_user_id(db: Session, user_id: UUID, limit: int = 50) -> List[tuple]:
    """
    ユーザーがいいねした投稿を取得（top_crud.pyの121-126行目の項目と合わせる）
    """
    return (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label('thumbnail_key'),
            ThumbnailAssets.duration_sec.label('duration_sec'),
            Likes.created_at.label('created_at')
        )
        .join(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(ThumbnailAssets, (Posts.id == ThumbnailAssets.post_id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL))
        .filter(Likes.user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)  # 公開済みの投稿のみ
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, ThumbnailAssets.storage_key, ThumbnailAssets.duration_sec, Likes.created_at)
        .order_by(desc(Likes.created_at))  # いいねした日時の新しい順
        .limit(limit)
        .all()
    )

def get_bookmarked_posts_by_user_id(db: Session, user_id: UUID) -> List[tuple]:
    """
    ユーザーがブックマークした投稿を取得
    """
    return (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label('thumbnail_key'),
            ThumbnailAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label('likes_count'),
            func.count(func.distinct(Comments.id)).label('comments_count'),
            Bookmarks.created_at.label('bookmarked_at')
        )
        .join(Bookmarks, Posts.id == Bookmarks.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(ThumbnailAssets, (Posts.id == ThumbnailAssets.post_id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .filter(Bookmarks.user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
            Bookmarks.created_at
        )
        .order_by(desc(Bookmarks.created_at))
        .all()
    )

def get_liked_posts_list_by_user_id(db: Session, user_id: UUID) -> List[tuple]:
    """
    ユーザーがいいねした投稿一覧を取得（カード表示用）
    """
    return (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label('thumbnail_key'),
            ThumbnailAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label('likes_count'),
            func.count(func.distinct(Comments.id)).label('comments_count'),
            Likes.created_at.label('liked_at')
        )
        .join(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(ThumbnailAssets, (Posts.id == ThumbnailAssets.post_id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .filter(Likes.user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
            Likes.created_at
        )
        .order_by(desc(Likes.created_at))
        .all()
    )

def get_bought_posts_by_user_id(db: Session, user_id: UUID) -> List[tuple]:
    """
    ユーザーが購入した投稿を取得
    """
    # サブクエリで投稿ごとの最新購入日時を取得（投稿IDのみでグループ化）
    latest_purchases = (
        db.query(
            Posts.id.label('post_id'),
            func.max(Purchases.created_at).label('latest_purchase_at')
        )
        .select_from(Purchases)
        .join(Plans, Purchases.plan_id == Plans.id)
        .join(PostPlans, Plans.id == PostPlans.plan_id)
        .join(Posts, PostPlans.post_id == Posts.id)
        .filter(Purchases.user_id == user_id)
        .filter(Purchases.deleted_at.is_(None))
        .group_by(Posts.id)
        .subquery()
    )

    return (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label('thumbnail_key'),
            ThumbnailAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label('likes_count'),
            func.count(func.distinct(Comments.id)).label('comments_count'),
            latest_purchases.c.latest_purchase_at.label('purchased_at')
        )
        .select_from(Posts)
        .join(latest_purchases, Posts.id == latest_purchases.c.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(ThumbnailAssets, (Posts.id == ThumbnailAssets.post_id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            ThumbnailAssets.duration_sec,
            latest_purchases.c.latest_purchase_at
        )
        .order_by(desc(latest_purchases.c.latest_purchase_at))
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

    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec'),
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        # post_plansテーブルとの結合
        .outerjoin(PostPlans, Posts.id == PostPlans.post_id)
        # サムネイル用のMediaAssets（kind=2）
        .outerjoin(ThumbnailAssets, (Posts.id == ThumbnailAssets.post_id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL))
        # メインビデオ用のMediaAssets（kind=4）
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .filter(active_post_cond)
        .group_by(
            Posts.id, 
            Users.profile_name,
            Profiles.username, 
            Profiles.avatar_url, 
            ThumbnailAssets.storage_key, 
            VideoAssets.duration_sec,
        )
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

def get_recent_posts(db: Session, limit: int = 5):
    """
    最新の投稿を取得（いいね数も含む）
    """
    now = func.now()
    active_post_cond = and_(
        Posts.status == PostStatus.APPROVED,
        Posts.deleted_at.is_(None),
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    return (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label('thumbnail_key'),
            func.count(Likes.post_id).label('likes_count'),
            VideoAssets.duration_sec.label('duration_sec')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        # post_plansテーブルとの結合
        .outerjoin(PostPlans, Posts.id == PostPlans.post_id)
        # サムネイル用のMediaAssets（kind=2）
        .outerjoin(ThumbnailAssets, (Posts.id == ThumbnailAssets.post_id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL))
        # メインビデオ用のMediaAssets（kind=4）
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        # いいね数を取得するためのLikesテーブル
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(active_post_cond)
        .group_by(
            Posts.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key,
            VideoAssets.duration_sec
        )
        .order_by(desc(Posts.created_at))
        .limit(limit)
        .all()
    )

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

    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)  # 公開済みの投稿のみ
        .filter(Posts.deleted_at.is_(None))  # 削除されていない投稿のみ
        .filter(active_post_cond)
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAssets.duration_sec)
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

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

    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_month_ago)  # 過去30日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAssets.duration_sec)
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

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

    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_week_ago)  # 過去7日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAssets.duration_sec)
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

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
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_day_ago)  # 過去1日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAssets.duration_sec)
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

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
        if hasattr(post, key) and value is not None:
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

def update_post_status(db: Session, post_id: UUID, status: int, authenticated_flg: int = None):
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
def _is_purchased(db: Session, user_id: UUID | None, post_id: UUID) -> bool:
    """
    ユーザーが投稿を購入しているかどうかを判定

    Args:
        db (Session): データベースセッション
        user_id (UUID | None): ユーザーID（Noneの場合は未購入扱い）
        post_id (UUID): 投稿ID

    Returns:
        bool: 購入済みの場合True、未購入の場合False
    """
    if user_id is None:
        return False
    return db.query(exists().where(
        Purchases.user_id == user_id,
        Purchases.post_id == post_id,
        Purchases.deleted_at.is_(None)  # 削除されていない購入のみ
    )).scalar()

def _get_post_and_creator_info(db: Session, post_id: str) -> tuple:
    """投稿とクリエイター情報を取得"""
    post = db.query(Posts).filter(
        Posts.id == post_id,
        Posts.deleted_at.is_(None)
    ).first()
    
    if not post:
        return None, None, None
    
    creator = (
        db.query(
            Users
        )
        .filter(
            Users.id == post.creator_user_id).first())
    creator_profile = db.query(Profiles).filter(Profiles.user_id == post.creator_user_id).first()
    
    return post, creator, creator_profile

def _get_post_categories(db: Session, post_id: str) -> list:
    """投稿のカテゴリ情報を取得"""
    return (
        db.query(Categories)
        .join(PostCategories, Categories.id == PostCategories.category_id)
        .filter(PostCategories.post_id == post_id)
        .filter(Categories.is_active == True)
        .all()
    )

def _get_likes_count(db: Session, post_id: str) -> int:
    """投稿のいいね数を取得"""
    return db.query(func.count(Likes.post_id)).filter(Likes.post_id == post_id).scalar() or 0

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
    
    #Planテーブルからプラン金額を取得（post_plansテーブルを経由）
    plans = (
        db.query(Plans)
        .join(PostPlans, Plans.id == PostPlans.plan_id)
        .filter(PostPlans.post_id == post_id)
        .all()
    )
    
    return {
        "price": price,
        "plans": plans
    }

def _get_media_info(db: Session, post_id: str, user_id: str | None) -> dict:
    """メディア情報を取得・処理"""
    media_assets = db.query(MediaAssets).filter(MediaAssets.post_id == post_id).all()
    is_entitlement = check_entitlement(db, user_id, post_id) if user_id else False

    set_media_kind = MediaAssetKind.MAIN_VIDEO if is_entitlement else MediaAssetKind.SAMPLE_VIDEO
    set_file_name = "_1080w.webp" if is_entitlement else "_blurred.webp"
    
    media_info = []
    for media_asset in media_assets:
        if media_asset.kind == MediaAssetKind.THUMBNAIL:
            thumbnail_key = f"{CDN_BASE_URL}/{media_asset.storage_key}"
        elif media_asset.kind == MediaAssetKind.IMAGES:
            media_info.append({
                "kind": media_asset.kind,
                "duration": media_asset.duration_sec,
                "media_assets_id": media_asset.id,
                "orientation": media_asset.orientation,
                "post_id": media_asset.post_id,
                "storage_key": f"{MEDIA_CDN_URL}/{media_asset.storage_key}{set_file_name}"
            })
        elif media_asset.kind == set_media_kind:
            media_info.append({
                "kind": media_asset.kind,
                "duration": media_asset.duration_sec,
                "media_assets_id": media_asset.id,
                "orientation": media_asset.orientation,
                "post_id": media_asset.post_id,
                "storage_key": f"{MEDIA_CDN_URL}/{media_asset.storage_key}"
            })
    
    return {
        "media_assets": media_assets,
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
                "url": f"{CDN_BASE_URL}/{media_asset.storage_key}"
            }
        elif media_asset.kind == MediaAssetKind.SAMPLE_VIDEO:
            if upload_flg:
                presign_url = presign_get("ingest", media_asset.storage_key)
                sample_video_url = presign_url['download_url']
            else:
                sample_video_url = f"{MEDIA_CDN_URL}/{media_asset.storage_key}"
                
            sample_video = {
                "kind": media_asset.kind,
                "storage_key": media_asset.storage_key,
                "url": sample_video_url,
                "duration": media_asset.duration_sec,
                "reject_comments": media_asset.reject_comments
            }
        elif media_asset.kind == MediaAssetKind.MAIN_VIDEO:
            if upload_flg:
                presign_url = presign_get("ingest", media_asset.storage_key)
                main_video_url = presign_url['download_url']
            else:
                main_video_url = f"{MEDIA_CDN_URL}/{media_asset.storage_key}"

            main_video = {
                "kind": media_asset.kind,
                "storage_key": media_asset.storage_key,
                "url": main_video_url,
                "duration": media_asset.duration_sec,
                "reject_comments": media_asset.reject_comments
            }
        elif media_asset.kind == MediaAssetKind.IMAGES:
            if upload_flg and media_asset.status in [MediaAssetStatus.PENDING, MediaAssetStatus.RESUBMIT, MediaAssetStatus.CONVERTING]:
                presign_url = presign_get("ingest", media_asset.storage_key)
                image_url = presign_url['download_url']
            else:
                image_url = f"{MEDIA_CDN_URL}/{media_asset.storage_key}_1080w.webp"
            images.append({
                "id": str(media_asset.id),  # IDをstringとして返す
                "kind": media_asset.kind,
                "storage_key": media_asset.storage_key,
                "url": image_url,
                "duration": media_asset.duration_sec,
                "orientation": media_asset.orientation,
                "reject_comments": media_asset.reject_comments
            })
        elif media_asset.kind == MediaAssetKind.OGP:
            ogp_image = {
                "kind": media_asset.kind,
                "storage_key": media_asset.storage_key,
                "url": f"{CDN_BASE_URL}/{media_asset.storage_key}",
                "reject_comments": media_asset.reject_comments
            }

    return {
        "thumbnail": thumbnail,
        "sample_video": sample_video,
        "main_video": main_video,
        "images": images,
        "ogp_image": ogp_image,
        "media_assets": media_assets
    }

def get_post_detail_for_creator(db: Session, post_id: UUID, creator_user_id: UUID) -> dict | None:
    """
    クリエイター自身の投稿詳細を取得（統計情報含む）
    """
    VideoAsset = aliased(MediaAssets)
    ThumbnailAsset = aliased(MediaAssets)
    OGPAsset = aliased(MediaAssets)

    result = (
        db.query(
            Posts,
            func.count(func.distinct(Likes.user_id)).label('likes_count'),
            func.count(func.distinct(Comments.id)).label('comments_count'),
            func.count(func.distinct(OrderItems.id)).label('purchase_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label('post_price'),
            func.min(Prices.currency).label('post_currency'),
            ThumbnailAsset.storage_key.label('thumbnail_key'),
            VideoAsset.duration_sec
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(ThumbnailAsset, (Posts.id == ThumbnailAsset.post_id) & (ThumbnailAsset.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAsset, (Posts.id == VideoAsset.post_id) & (VideoAsset.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .outerjoin(OrderItems, Posts.id == OrderItems.post_id)
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
            VideoAsset.duration_sec
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
    db: Session,
    post_id: UUID,
    creator_user_id: UUID,
    update_data: dict
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
    allowed_fields = ['description', 'status', 'visibility', 'scheduled_at', 'expiration_at']

    for field, value in update_data.items():
        if field in allowed_fields and value is not None:
            setattr(post, field, value)

    # ステータスがDELETEDの場合、deleted_atを設定
    if 'status' in update_data and update_data['status'] == PostStatus.DELETED:
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
            func.count(Follows.creator_user_id).label('followers_count'),
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
        .order_by(desc('likes_count'))
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
            func.count(Follows.creator_user_id).label('followers_count'),
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
        .order_by(desc('likes_count'))
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
            func.count(Follows.creator_user_id).label('followers_count'),
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
        .order_by(desc('likes_count'))
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
            func.count(Follows.creator_user_id).label('followers_count'),
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
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

def get_ranking_creators_overall_detail_all_time(db: Session, page: int = 1, limit: int = 500):
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
            func.count(Follows.creator_user_id).label('followers_count'),
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
        .order_by(desc('likes_count'))
        .offset(offset)
        .limit(limit)
        .all()
    )

def get_ranking_creators_overall_detail_daily(db: Session, page: int = 1, limit: int = 500):
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
            func.count(Follows.creator_user_id).label('followers_count'),
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
        .order_by(desc('likes_count'))
        .offset(offset)
        .limit(limit)
        .all()
    )

def get_ranking_creators_overall_detail_weekly(db: Session, page: int = 1, limit: int = 500):
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
            func.count(Follows.creator_user_id).label('followers_count'),
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
        .order_by(desc('likes_count'))
        .offset(offset)
        .limit(limit)
        .all()
    )

def get_ranking_creators_overall_detail_monthly(db: Session, page: int = 1, limit: int = 500):
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
            func.count(Follows.creator_user_id).label('followers_count'),
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
        .order_by(desc('likes_count'))
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_post_by_id(db: Session, post_id: str) -> Dict[str, Any]:
    """
    投稿IDをキーにして投稿情報、ユーザー情報、メディア情報を取得
    """
    try:
        # UUIDに変換
        post_uuid = post_id
    except ValueError:
        return None

    # 投稿情報と関連データを取得
    result = (
        db.query(
            Posts,
            Users,
            Profiles,
            MediaAssets,
            MediaRenditionJobs.output_key.label('rendition_output_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, Posts.id == MediaAssets.post_id)
        .outerjoin(MediaRenditionJobs, MediaAssets.id == MediaRenditionJobs.asset_id)
        .filter(Posts.id == post_uuid)
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
                'id': str(row.MediaAssets.id),
                'status': row.MediaAssets.status,
                'post_id': str(row.MediaAssets.post_id),
                'kind': row.MediaAssets.kind,
                'storage_key': row.MediaAssets.storage_key,
                'file_size': row.MediaAssets.bytes,
                'reject_comments': row.MediaAssets.reject_comments,
                'duration': float(row.MediaAssets.duration_sec) if row.MediaAssets.duration_sec else None,
                'duration_sec': float(row.MediaAssets.duration_sec) if row.MediaAssets.duration_sec else None,
                'orientation': row.MediaAssets.orientation,
                'sample_type': row.MediaAssets.sample_type,
                'sample_start_time': float(row.MediaAssets.sample_start_time) if row.MediaAssets.sample_start_time else None,
                'sample_end_time': float(row.MediaAssets.sample_end_time) if row.MediaAssets.sample_end_time else None,
                'created_at': row.MediaAssets.created_at.isoformat() if row.MediaAssets.created_at else None,
                'updated_at': None
            }
            
            # 重複を避けるため、既に存在するかチェック
            if not any(ma['id'] == media_asset['id'] for ma in media_assets):
                media_assets.append(media_asset)

        if row.rendition_output_key:
            rendition_job = {
                'output_key': row.rendition_output_key
            }
            
            # 重複を避けるため、既に存在するかチェック
            if not any(rj['output_key'] == rendition_job['output_key'] for rj in rendition_jobs):
                rendition_jobs.append(rendition_job)

    # 価格情報を取得（単品販売）
    single_price_data = db.query(Prices.price).filter(
        Prices.post_id == post_uuid,
        Prices.is_active == True
    ).first()

    # プラン情報を取得
    plan_data = (
        db.query(
            Plans.id,
            Plans.name,
            Plans.price
        )
        .join(PostPlans, Plans.id == PostPlans.plan_id)
        .filter(
            PostPlans.post_id == post_uuid,
            Plans.deleted_at.is_(None),
        )
        .all()
    )

    # プラン情報をリスト形式に整形
    plans_list = [
        {
            'plan_id': str(plan.id),
            'plan_name': plan.name,
            'price': plan.price
        }
        for plan in plan_data
    ] if plan_data else None

    # 指定された内容を返却
    return {
        # 投稿情報
        'id': str(post.id),
        'description': post.description,
        'status': post.status,
        'created_at': post.created_at.isoformat() if post.created_at else None,
        'authenticated_flg': post.authenticated_flg,
        # ユーザー情報
        'user_id': str(user.id),
        'profile_name': user.profile_name,
        # プロフィール情報
        'username': profile.username,
        'profile_avatar_url': f"{CDN_BASE_URL}/{profile.avatar_url}" if profile.avatar_url else None,
        'post_type': post.post_type,
        # メディアアセット情報
        'media_assets': {
            ma['id']: {
                'kind': ma['kind'],
                'storage_key': ma['storage_key'],
                'status': ma['status'],
                'reject_comments': ma['reject_comments'],
                'duration_sec': ma.get('duration_sec'),
                'orientation': ma.get('orientation'),
                'sample_type': ma.get('sample_type'),
                'sample_start_time': ma.get('sample_start_time'),
                'sample_end_time': ma.get('sample_end_time'),
            }
            for ma in media_assets if ma['storage_key']
        },  # メディアアセットIDをキー、kindとstorage_keyを含む辞書を値とする辞書
        # 価格情報
        'single_price': single_price_data[0] if single_price_data else None,
        'plans': plans_list
    }


# ========== ランキング用 各ジャンル==========
def get_ranking_posts_detail_categories_all_time(db: Session, category: str, page: int = 1, limit: int = 500):
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
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
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

    return result

def get_ranking_posts_detail_categories_daily(db: Session, category: str, page: int = 1, limit: int = 500):
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
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
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
            Likes.created_at >= one_day_ago,
        )
        .group_by(
            Categories.id,
            Categories.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
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

    return result

def get_ranking_posts_detail_categories_weekly(db: Session, category: str, page: int = 1, limit: int = 500):
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
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
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
            Likes.created_at >= one_week_ago,
        )
        .group_by(
            Categories.id,
            Categories.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
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

    return result

def get_ranking_posts_detail_categories_monthly(db: Session, category: str, page: int = 1, limit: int = 500):
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
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
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
            Likes.created_at >= one_month_ago,
        )
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .group_by(
            Categories.id,
            Categories.name,
            Posts.id.label("post_id"),
            Posts.post_type.label("post_type"),
            Posts.creator_user_id.label("creator_user_id"),
            Users.profile_name.label("profile_name"),
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

    return result

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
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
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
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),

            func.row_number()
            .over(
                partition_by=Categories.id,
                order_by=func.count(Likes.post_id).desc()
            )
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
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
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
                # Likes.created_at >= func.date_trunc("day", func.now()),
            ),
        )
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .group_by(
            Categories.id,
            Categories.name,
            Genres.id,
            Genres.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
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
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
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
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"),
            func.count(Likes.post_id).label("likes_count"),

            func.row_number()
            .over(
                partition_by=Categories.id,
                order_by=func.count(Likes.post_id).desc()
            )
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
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
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
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .group_by(
            Categories.id,
            Categories.name,
            Genres.id,
            Genres.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
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
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
                active_post_cond
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
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"), 
            func.count(Likes.post_id).label("likes_count"),

            func.row_number()
            .over(
                partition_by=Categories.id,
                order_by=func.count(Likes.post_id).desc()
            )
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
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
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
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .group_by(
            Categories.id,
            Categories.name,
            Genres.id,
            Genres.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
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
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
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
            Posts.post_type.label("post_type"),
            Posts.description.label("description"),
            Users.profile_name.label("profile_name"),
            Profiles.username.label("username"),
            Profiles.avatar_url.label("avatar_url"),
            MediaAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec.label("duration_sec"), 
            func.count(Likes.post_id).label("likes_count"),

            func.row_number()
            .over(
                partition_by=Categories.id,
                order_by=func.count(Likes.post_id).desc()
            )
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
                Posts.status == PostStatus.APPROVED,
                Posts.deleted_at.is_(None),
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
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .group_by(
            Categories.id,
            Categories.name,
            Genres.id,
            Genres.name,
            Posts.id,
            Posts.creator_user_id,
            Users.profile_name,
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

def get_ranking_posts_detail_overall_all_time(db: Session, page: int = 1, limit: int = 500):
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
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec'),
        )
        .outerjoin(Users, Posts.creator_user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)  # 公開済みの投稿のみ
        .filter(Posts.deleted_at.is_(None))  # 削除されていない投稿のみ
        .filter(active_post_cond)
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAssets.duration_sec)
        .order_by(desc('likes_count'))
        .offset(offset)
        .limit(limit)
        .all()
    )

def get_ranking_posts_detail_overall_monthly(db: Session, page: int = 1, limit: int = 500):
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
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec'),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_month_ago)  # 過去30日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAssets.duration_sec)
        .order_by(desc('likes_count'))
        .offset(offset)
        .limit(limit)
        .all()
    )

def get_ranking_posts_detail_overall_weekly(db: Session, page: int = 1, limit: int = 500):
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
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec'),
        )
        .outerjoin(Users, Posts.creator_user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.deleted_at.is_(None))
        .filter(active_post_cond)
        .filter(Posts.created_at >= one_week_ago)  # 過去7日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAssets.duration_sec)
        .order_by(desc('likes_count'))
        .offset(offset)
        .limit(limit)
        .all()
    )

def get_ranking_posts_detail_overall_daily(db: Session, page: int = 1, limit: int = 500):
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
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            VideoAssets.duration_sec.label('duration_sec'),
        )
        .outerjoin(Users, Posts.creator_user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(VideoAssets, (Posts.id == VideoAssets.post_id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.deleted_at.is_(None))
        .filter(active_post_cond)
        .filter(Posts.created_at >= one_day_ago)  # 過去1日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key, VideoAssets.duration_sec)
        .order_by(desc('likes_count'))
        .offset(offset)
        .limit(limit)
        .all()
    )

def add_notification_for_post(
    db: Session, 
    post: Posts = None, 
    post_id: str = None,
    user_id: UUID = None, 
    liked_user_id: UUID = None,
    type: str = "approved"
) -> None:
    """ 投稿に対する通知を追加

    Args:
        db: データベースセッション
        post_id: 投稿ID
        user_id: ユーザーID
        type: 通知タイプ "approved" | "rejected" | "like"
    """
    try:
        if type == "approved":
            try:
                profiles = db.query(Profiles).filter(Profiles.user_id == post.creator_user_id).first()
                message = POST_APPROVED_MD.replace("-name-", profiles.username).replace("--post-url--", f"{os.environ.get('FRONTEND_URL')}/post/detail?post_id={post.id}")
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
            except Exception as e:
                db.rollback()
                logger.error(f"Add notification for post approved error: {e}")
                pass
        elif type == "rejected":
            try:
                post = db.query(Posts).filter(Posts.id == post_id).first()
                profiles = db.query(Profiles).filter(Profiles.user_id == post.creator_user_id).first()
                message = POST_REJECTED_MD.replace("-name-", profiles.username).replace("--post-url--", f"{os.environ.get('FRONTEND_URL')}/account/post/{post.id}")
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
            except Exception as e:
                db.rollback()
                logger.error(f"Add notification for post rejected error: {e}")
                pass
        elif type == "like":
            liked_user_profile = db.query(Profiles).filter(Profiles.user_id == liked_user_id).first()
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
    media_asset = db.query(MediaAssets).filter(
        and_(
            MediaAssets.post_id == post_id,
            MediaAssets.kind == MediaAssetKind.OGP,
        )
    ).first()
    

    if not media_asset:
        return None

    return f"{CDN_BASE_URL}/{media_asset.storage_key}"

def add_mail_notification_for_post(
    db: Session, 
    post_id: UUID = None, 
    type: str = "approved"
) -> None:
    """ 投稿に対するメール通知を追加

    Args:
        db: データベースセッション
        user_id: ユーザーID
        type: 通知タイプ "approved" | "rejected"
    """
    try:
        user = (
            db.query(
                Users,
                Profiles.username,
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

        if not user:
            raise Exception("Can not query user settings")
        if type == "approved":
            if ((user.settings is None) or (user.settings.get("postApprove", True) == True) or (user.settings.get("postApprove", True) is None)):
                send_post_approval_email(user.Users.email, user.username, user.Posts.id)
        elif type == "rejected":
            if ((user.settings is None) or (user.settings.get("postApprove", True) == True) or (user.settings.get("postApprove", True) is None)):
                send_post_rejection_email(user.Users.email, user.username, user.Posts.reject_comments, user.Posts.id)
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
            Profiles.avatar_url
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .filter(Posts.id == post_id)
        .filter(Posts.deleted_at.is_(None))
        .first()
    )

    if not result:
        return None

    # OGP画像URLを取得
    # 優先順位: generation_media (kind=2) → thumbnail → デフォルト画像
    ogp_image_url = None

    # 1. generation_mediaからOGP画像を取得
    generation_media = db.query(GenerationMedia).filter(
        GenerationMedia.post_id == post_id,
        GenerationMedia.kind == GenerationMediaKind.POST_IMAGE
    ).first()

    if generation_media:
        ogp_image_url = f"{CDN_BASE_URL}/{generation_media.storage_key}"
    else:
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
            "avatar_url": avatar_url
        },
        "created_at": result.created_at
    }

