import os
import re
from fastapi import HTTPException
from sqlalchemy.orm import Session, aliased
from sqlalchemy import func, desc, exists
from app.models.posts import Posts
from app.models.social import Likes, Bookmarks, Comments
from uuid import UUID
from datetime import datetime
from app.constants.enums import PostStatus, MediaAssetKind
from app.schemas.post import PostCreateRequest
from app.models.post_categories import PostCategories
from app.models.categories import Categories
from typing import List
from app.models.user import Users
from app.models.profiles import Profiles
from app.models.media_assets import MediaAssets
from app.models.plans import Plans, PostPlans   
from app.models.prices import Prices
from app.models.media_renditions import MediaRenditions
from app.crud.entitlements_crud import check_entitlement
from app.api.commons.utils import get_video_duration
from app.constants.enums import PlanStatus
from app.models.purchases import Purchases
from datetime import datetime, timedelta

# エイリアスを定義
ThumbnailAssets = aliased(MediaAssets)
VideoAssets = aliased(MediaAssets)
# ========== 投稿管理 ==========

MEDIA_CDN_URL = os.getenv("MEDIA_CDN_URL")
CDN_BASE_URL = os.getenv("CDN_BASE_URL")


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

def get_posts_by_category_slug(db: Session, slug: str) -> List[Posts]:
    """
    カテゴリーに紐づく投稿を取得
    """
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(PostCategories, Posts.id == PostCategories.post_id)
        .join(Categories, PostCategories.category_id == Categories.id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Categories.slug == slug)
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc(Posts.created_at))
        .all()
    )

def get_post_status_by_user_id(db: Session, user_id: UUID) -> dict:
    """
    ユーザーの投稿ステータスを取得
    """
    
    # 審査中の投稿を取得
    pending_posts = (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label('post_price'),  # 最安値を取得
            func.min(Prices.currency).label('post_currency'),  # 最安値の通貨を取得
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(PostPlans, Posts.id == PostPlans.post_id)
        .outerjoin(Plans, PostPlans.plan_id == Plans.id)
        .outerjoin(Prices, Plans.id == Prices.plan_id)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.PENDING)
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc(Posts.created_at))
        .all()
    )

    # 拒否された投稿を取得
    rejected_posts = (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label('post_price'),  # 最安値を取得
            func.min(Prices.currency).label('post_currency'),  # 最安値の通貨を取得
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(PostPlans, Posts.id == PostPlans.post_id)
        .outerjoin(Plans, PostPlans.plan_id == Plans.id)
        .outerjoin(Prices, Plans.id == Prices.plan_id)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.REJECTED)
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc(Posts.created_at))
        .all()
    )

    # 非公開の投稿を取得
    unpublished_posts = (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label('post_price'),  # 最安値を取得
            func.min(Prices.currency).label('post_currency'),  # 最安値の通貨を取得
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(PostPlans, Posts.id == PostPlans.post_id)
        .outerjoin(Plans, PostPlans.plan_id == Plans.id)
        .outerjoin(Prices, Plans.id == Prices.plan_id)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.UNPUBLISHED)
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc(Posts.created_at))
        .all()
    )

    # 削除された投稿を取得
    deleted_posts = (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label('post_price'),  # 最安値を取得
            func.min(Prices.currency).label('post_currency'),  # 最安値の通貨を取得
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(PostPlans, Posts.id == PostPlans.post_id)
        .outerjoin(Plans, PostPlans.plan_id == Plans.id)
        .outerjoin(Prices, Plans.id == Prices.plan_id)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.DELETED)
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc(Posts.created_at))
        .all()
    )

    # 公開された投稿を取得
    approved_posts = (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            func.min(Prices.price).label('post_price'),  # 最安値を取得
            func.min(Prices.currency).label('post_currency'),  # 最安値の通貨を取得
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(PostPlans, Posts.id == PostPlans.post_id)
        .outerjoin(Plans, PostPlans.plan_id == Plans.id)
        .outerjoin(Prices, Plans.id == Prices.plan_id)
        .filter(Posts.creator_user_id == user_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc(Posts.created_at))
        .all()
    )

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
        .filter(Posts.status == PostStatus.APPROVED)
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
        .filter(Posts.status == PostStatus.APPROVED)
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

# ========== ランキング用 ==========

def get_ranking_posts_all_time(db: Session, limit: int = 500):
    """
    全期間でいいね数が多い投稿を取得
    """
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        # TODO: 公開済みの投稿のみにする
        .filter(Posts.status == PostStatus.APPROVED)  # 公開済みの投稿のみ
        .filter(Posts.deleted_at.is_(None))  # 削除されていない投稿のみ
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

def get_ranking_posts_monthly(db: Session, limit: int = 50):
    """
    月間でいいね数が多い投稿を取得
    """
    one_month_ago = datetime.now() - timedelta(days=30)
    
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        # .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_month_ago)  # 過去30日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

def get_ranking_posts_weekly(db: Session, limit: int = 50):
    """
    週間でいいね数が多い投稿を取得
    """
    one_week_ago = datetime.now() - timedelta(days=7)
    
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_week_ago)  # 過去7日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
        .order_by(desc('likes_count'))
        .limit(limit)
        .all()
    )

def get_ranking_posts_daily(db: Session, limit: int = 50):
    """
    日間でいいね数が多い投稿を取得
    """
    one_day_ago = datetime.now() - timedelta(days=1)
    
    return (
        db.query(
            Posts,
            func.count(Likes.post_id).label('likes_count'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key')
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(MediaAssets, (Posts.id == MediaAssets.post_id) & (MediaAssets.kind == MediaAssetKind.THUMBNAIL))
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.created_at >= one_day_ago)  # 過去1日以内のいいね
        .group_by(Posts.id, Users.profile_name, Profiles.username, Profiles.avatar_url, MediaAssets.storage_key)
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

    post.updated_at = datetime.now()
    db.add(post)
    db.flush()
    return post

def update_post_status(db: Session, post_id: UUID, status: int):
    """
    投稿のステータスを更新
    """
    post = db.query(Posts).filter(Posts.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    
    post.status = status
    post.updated_at = datetime.now()
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
    set_file_name = "_1080w.webp" if is_entitlement else "_mosaic.webp"
    
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