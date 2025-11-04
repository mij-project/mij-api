from sqlalchemy.orm import Session, aliased
from app.models.plans import Plans
from app.models.subscriptions import Subscriptions
from uuid import UUID
from typing import List, Optional
from app.schemas.plan import PlanCreateRequest, PlanResponse, SubscribedPlanResponse
from app.constants.enums import PlanStatus, PlanLifecycleStatus
from datetime import datetime
from app.models.profiles import Profiles
from app.models.plans import PostPlans
from app.models.posts import Posts
from app.models.media_assets import MediaAssets
from app.models.social import Likes, Comments
from app.models.prices import Prices
from app.constants.enums import MediaAssetKind
from app.api.commons.utils import get_video_duration
from app.models.user import Users
from sqlalchemy import func, and_
import os

BASE_URL = os.getenv("CDN_BASE_URL")
from app.constants.enums import PostStatus

def get_plan_by_user_id(db: Session, user_id: UUID) -> dict:
    """
    ユーザーが加入中のプラン数と詳細を取得
    """

    # サブスクリプション中のプラン（type=2）を取得
    subscribed_subscriptions = (
        db.query(Subscriptions)
        .join(Plans, Subscriptions.plan_id == Plans.id)
        .filter(
            Subscriptions.user_id == user_id,
            Plans.deleted_at.is_(None),  # 削除されていないプラン
            Subscriptions.status == 1,  # アクティブなサブスクリプション
            Subscriptions.canceled_at.is_(None)  # キャンセルされていないサブスクリプション
        )
        .all()
    )

    subscribed_plan_count = len(subscribed_subscriptions)
    subscribed_total_price = 0
    subscribed_plan_names = []
    subscribed_plan_details = []

    # 加入中のプランの詳細情報を取得
    for subscription in subscribed_subscriptions:
        # プランから価格情報を取得（Pricesテーブルではなくplansテーブルから）
        plan_price = subscription.plan.price

        # クリエイター情報を取得
        creator_profile = (
            db.query(
                Profiles.avatar_url,
                Profiles.username,
                Users.profile_name,
            )
            .join(Users, Profiles.user_id == Users.id)
            .filter(
                Users.id == subscription.plan.creator_user_id,
                Profiles.user_id == subscription.plan.creator_user_id,
                Users.deleted_at.is_(None)
            )
            .first()
        )

        # プランに紐づく投稿数を取得
        post_count = (
            db.query(
                func.count(PostPlans.post_id)
            )
            .join(Posts, PostPlans.post_id == Posts.id)
            .filter(
                PostPlans.plan_id == subscription.plan_id,
                Posts.deleted_at.is_(None),
                Posts.status == PostStatus.APPROVED
            ).scalar()
        )

        # プランに紐づく投稿のサムネイルを取得（最大4件）
        thumbnails = (
            db.query(MediaAssets.storage_key)
            .join(Posts, MediaAssets.post_id == Posts.id)
            .join(PostPlans, Posts.id == PostPlans.post_id)
            .filter(
                PostPlans.plan_id == subscription.plan_id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
                Posts.deleted_at.is_(None),
                Posts.status == PostStatus.APPROVED
            )
            .order_by(Posts.created_at.desc())
            .limit(4)
            .all()
        )

        thumbnail_keys = [thumb.storage_key for thumb in thumbnails]

        subscribed_total_price += plan_price
        subscribed_plan_names.append(subscription.plan.name)

        # 詳細情報を追加
        subscribed_plan_details.append({
            "subscription_id": str(subscription.id),
            "plan_id": str(subscription.plan.id),
            "plan_name": subscription.plan.name,
            "plan_description": subscription.plan.description,
            "price": plan_price,
            "subscription_created_at": subscription.created_at,
            "current_period_start": subscription.current_period_start,
            "current_period_end": subscription.current_period_end,
            "creator_avatar_url": creator_profile.avatar_url if creator_profile and creator_profile.avatar_url else None,
            "creator_username": creator_profile.username if creator_profile else None,
            "creator_profile_name": creator_profile.profile_name if creator_profile else None,
            "post_count": post_count or 0,
            "thumbnail_keys": thumbnail_keys
        })

    return {
        "plan_count": subscribed_plan_count,
        "total_price": subscribed_total_price,
        "subscribed_plan_count": subscribed_plan_count,
        "subscribed_total_price": subscribed_total_price,
        "subscribed_plan_names": subscribed_plan_names,
        "subscribed_plan_details": subscribed_plan_details
    }

def create_plan(db: Session, plan_data: dict, post_ids: List[UUID] = None) -> Plans:
    """
    プランを作成
    """
    # post_idsは別途処理するので削除
    plan_data_copy = {k: v for k, v in plan_data.items() if k != 'post_ids'}

    db_plan = Plans(**plan_data_copy)
    db.add(db_plan)
    db.flush()

    # 投稿を紐付ける
    if post_ids:
        for post_id in post_ids:
            post_plan = PostPlans(plan_id=db_plan.id, post_id=post_id)
            db.add(post_plan)
        db.flush()

    return db_plan

def get_user_plans(db: Session, user_id: UUID) -> List[dict]:
    """
    ユーザーのプラン一覧を取得
    """
    plans = (
        db.query(Plans)
        .filter(
            Plans.creator_user_id == user_id,
            Plans.deleted_at.is_(None),
            Plans.status != PlanLifecycleStatus.DELETED
        )
        .order_by(Plans.display_order.asc().nullslast(), Plans.created_at.desc())
    ).all()

    # レスポンス内容を整形する
    plans_response = []

    if plans:
        for plan in plans:
            # 投稿数を取得
            post_count = (
                db.query(func.count(PostPlans.post_id))
                .join(Posts, PostPlans.post_id == Posts.id)
                .filter(
                    PostPlans.plan_id == plan.id,
                    Posts.deleted_at.is_(None),
                    Posts.status == PostStatus.APPROVED
                )
                .scalar() or 0
            )

            # 加入者数を取得
            subscriber_count = (
                db.query(func.count(Subscriptions.id))
                .filter(
                    Subscriptions.plan_id == plan.id,
                    Subscriptions.status == 1,
                    Subscriptions.canceled_at.is_(None)
                )
                .scalar() or 0
            )

            plans_response.append({
                "id": plan.id,
                "name": plan.name,
                "description": plan.description,
                "price": plan.price,
                "type": plan.type,
                "display_order": plan.display_order,
                "welcome_message": plan.welcome_message,
                "post_count": post_count,
                "subscriber_count": subscriber_count
            })

    return plans_response

def get_plan_by_id(db: Session, plan_id: UUID) -> Plans:
    """
    プランをIDで取得
    """
    return db.query(Plans).filter(Plans.id == plan_id).first()

def get_plan_detail(db: Session, plan_id: UUID, current_user_id: UUID) -> dict:
    """
    プラン詳細情報を取得
    """
    # プラン情報を取得
    plan = (
        db.query(Plans)
        .filter(
            Plans.id == plan_id,
            Plans.deleted_at.is_(None)
        )
        .first()
    )

    if not plan:
        return None

    # クリエイター情報を取得
    creator_info = (
        db.query(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(Users.id == plan.creator_user_id)
        .first()
    )

    # プランの投稿数を取得
    post_count = (
        db.query(func.count(PostPlans.post_id))
        .join(Posts, PostPlans.post_id == Posts.id)
        .filter(
            PostPlans.plan_id == plan_id,
            Posts.deleted_at.is_(None),
            Posts.status == PostStatus.APPROVED
        )
        .scalar()
    )

    # サブスクリプション状態を確認
    is_subscribed = (
        db.query(Subscriptions)
        .filter(
            Subscriptions.user_id == current_user_id,
            Subscriptions.plan_id == plan_id,
            Subscriptions.status == 1,
            Subscriptions.canceled_at.is_(None)
        )
        .first() is not None
    )

    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "price": plan.price,
        "creator_id": creator_info.id if creator_info else None,
        "creator_name": creator_info.profile_name if creator_info else "",
        "creator_username": creator_info.username if creator_info else "",
        "creator_avatar_url": f"{BASE_URL}/{creator_info.avatar_url}" if creator_info and creator_info.avatar_url else None,
        "creator_cover_url": f"{BASE_URL}/{creator_info.cover_url}" if creator_info and creator_info.cover_url else None,
        "post_count": post_count or 0,
        "is_subscribed": is_subscribed
    }

def get_plan_posts_paginated(db: Session, plan_id: UUID, current_user_id: UUID, page: int = 1, per_page: int = 20):
    """
    プランの投稿を ページネーション付きで取得
    """
    offset = (page - 1) * per_page

    # サムネイルと動画用のエイリアスを作成
    ThumbnailAssets = aliased(MediaAssets)
    VideoAssets = aliased(MediaAssets)

    # 投稿の総数を取得
    total = (
        db.query(func.count(Posts.id))
        .join(PostPlans, Posts.id == PostPlans.post_id)
        .filter(
            PostPlans.plan_id == plan_id,
            Posts.deleted_at.is_(None),
            Posts.status == PostStatus.APPROVED
        )
        .scalar()
    )

    # 投稿データを取得
    posts_query = (
        db.query(
            Posts,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            ThumbnailAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec,
            func.count(func.distinct(Likes.user_id)).label("likes_count"),
            func.count(func.distinct(Comments.id)).label("comments_count"),
            Posts.created_at,
            Prices.price,
            Prices.currency
        )
        .join(PostPlans, Posts.id == PostPlans.post_id)
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(
            ThumbnailAssets,
            (ThumbnailAssets.post_id == Posts.id) & (ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL)
        )
        .outerjoin(
            VideoAssets,
            (VideoAssets.post_id == Posts.id) & (VideoAssets.kind == MediaAssetKind.MAIN_VIDEO)
        )
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .outerjoin(Comments, Posts.id == Comments.post_id)
        .outerjoin(Prices, Posts.id == Prices.post_id)
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
            VideoAssets.duration_sec,
            Posts.created_at,
            Prices.price,
            Prices.currency
        )
        .order_by(Posts.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )

    posts = []
    for post, profile_name, username, avatar_url, thumbnail_key, duration_sec, likes_count, comments_count, created_at, price, currency in posts_query:
        posts.append({
            "id": post.id,
            "thumbnail_url": f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None,
            "title": post.description or "",
            "creator_avatar": f"{BASE_URL}/{avatar_url}" if avatar_url else None,
            "creator_name": profile_name,
            "creator_username": username,
            "likes_count": likes_count or 0,
            "comments_count": comments_count or 0,
            "duration": get_video_duration(duration_sec) if duration_sec else None,
            "is_video": (post.post_type == 1),
            "created_at": created_at,
            "price": price,
            "currency": currency
        })

    has_next = (offset + per_page) < total

    return {
        "posts": posts,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_next": has_next
    }
def update_plan(db: Session, plan_id: UUID, update_data: dict) -> Optional[Plans]:
    """
    プランを更新
    """
    plan = db.query(Plans).filter(Plans.id == plan_id, Plans.deleted_at.is_(None)).first()
    if not plan:
        return None
    
    for key, value in update_data.items():
        if hasattr(plan, key) and value is not None:
            setattr(plan, key, value)
    
    plan.updated_at = datetime.now()
    db.flush()
    return plan

def request_plan_deletion(db: Session, plan_id: UUID) -> Optional[Plans]:
    """
    プランの削除を申請
    """
    plan = db.query(Plans).filter(Plans.id == plan_id, Plans.deleted_at.is_(None)).first()
    if not plan:
        return None
    
    plan.status = PlanLifecycleStatus.DELETE_REQUESTED
    plan.updated_at = datetime.now()
    db.flush()
    return plan

def get_plan_subscribers_paginated(db: Session, plan_id: UUID, page: int = 1, per_page: int = 20) -> dict:
    """
    プランの加入者一覧をページネーション付きで取得
    """
    offset = (page - 1) * per_page
    
    # 加入者の総数を取得
    total = (
        db.query(func.count(Subscriptions.id))
        .filter(
            Subscriptions.plan_id == plan_id,
            Subscriptions.status == 1,
            Subscriptions.canceled_at.is_(None)
        )
        .scalar()
    )
    
    # 加入者データを取得
    subscribers_query = (
        db.query(
            Users.id,
            Profiles.username,
            Users.profile_name,
            Profiles.avatar_url,
            Subscriptions.created_at,
            Subscriptions.current_period_end
        )
        .join(Subscriptions, Users.id == Subscriptions.user_id)
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(
            Subscriptions.plan_id == plan_id,
            Subscriptions.status == 1,
            Subscriptions.canceled_at.is_(None)
        )
        .order_by(Subscriptions.created_at.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )
    
    subscribers = []
    for user_id, username, profile_name, avatar_url, subscribed_at, current_period_end in subscribers_query:
        subscribers.append({
            "user_id": user_id,
            "username": username,
            "profile_name": profile_name,
            "avatar_url": f"{BASE_URL}/{avatar_url}" if avatar_url else None,
            "subscribed_at": subscribed_at,
            "current_period_end": current_period_end
        })
    
    has_next = (offset + per_page) < total
    
    return {
        "subscribers": subscribers,
        "total": total,
        "page": page,
        "per_page": per_page,
        "has_next": has_next
    }

def add_posts_to_plan(db: Session, plan_id: UUID, post_ids: List[UUID]) -> bool:
    """
    プランに投稿を紐付ける（既存の紐付けは削除してから新規追加）
    """
    # 既存の紐付けを削除
    db.query(PostPlans).filter(PostPlans.plan_id == plan_id).delete()
    
    # 新規紐付けを追加
    for post_id in post_ids:
        post_plan = PostPlans(plan_id=plan_id, post_id=post_id)
        db.add(post_plan)
    
    db.flush()
    return True

def reorder_plans(db: Session, creator_user_id: UUID, plan_orders: List) -> bool:
    """
    プランの並び順を更新
    """
    for item in plan_orders:
        # Pydanticモデルの場合とdictの場合の両方に対応
        if hasattr(item, 'plan_id'):
            plan_id_str = item.plan_id
            display_order = item.display_order
        else:
            plan_id_str = item["plan_id"]
            display_order = item["display_order"]

        # 文字列をUUIDに変換
        try:
            plan_id = UUID(plan_id_str) if isinstance(plan_id_str, str) else plan_id_str
        except (ValueError, AttributeError) as e:
            print(f"無効なUUID: {plan_id_str}, エラー: {e}")
            continue

        plan = db.query(Plans).filter(
            Plans.id == plan_id,
            Plans.creator_user_id == creator_user_id,
            Plans.deleted_at.is_(None)
        ).first()

        if plan:
            plan.display_order = display_order
            plan.updated_at = datetime.now()

    db.flush()
    return True

def get_creator_posts_for_plan(db: Session, creator_user_id: UUID, plan_id: Optional[UUID] = None) -> List[dict]:
    """
    クリエイターの投稿一覧を取得（プラン作成・編集用）
    plan_idが指定されている場合は、そのプランに含まれている投稿にチェックマークを付ける
    """
    ThumbnailAssets = aliased(MediaAssets)
    VideoAssets = aliased(MediaAssets)
    
    # 投稿データを取得
    posts_query = (
        db.query(
            Posts,
            ThumbnailAssets.storage_key.label("thumbnail_key"),
            VideoAssets.duration_sec
        )
        .outerjoin(
            ThumbnailAssets,
            and_(ThumbnailAssets.post_id == Posts.id, ThumbnailAssets.kind == MediaAssetKind.THUMBNAIL)
        )
        .outerjoin(
            VideoAssets,
            and_(VideoAssets.post_id == Posts.id, VideoAssets.kind == MediaAssetKind.MAIN_VIDEO)
        )
        .filter(
            Posts.creator_user_id == creator_user_id,
            Posts.deleted_at.is_(None),
            Posts.status == PostStatus.APPROVED
        )
        .order_by(Posts.created_at.desc())
        .all()
    )
    
    # プランに含まれている投稿IDを取得
    included_post_ids = set()
    if plan_id:
        included_posts = db.query(PostPlans.post_id).filter(PostPlans.plan_id == plan_id).all()
        included_post_ids = {post_id for (post_id,) in included_posts}
    
    posts = []
    for post, thumbnail_key, duration_sec in posts_query:
        posts.append({
            "id": post.id,
            "thumbnail_url": f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None,
            "title": post.description or "",
            "duration": get_video_duration(duration_sec) if duration_sec else None,
            "is_video": (post.post_type == 1),
            "created_at": post.created_at,
            "is_included": post.id in included_post_ids
        })
    
    return posts