from sqlalchemy.orm import Session
from app.models.plans import Plans
from app.models.subscriptions import Subscriptions
from uuid import UUID
from typing import List
from app.schemas.plan import PlanCreateRequest, PlanResponse, SubscribedPlanResponse
from app.constants.enums import PlanStatus
from datetime import datetime
from app.models.profiles import Profiles
from app.models.plans import PostPlans
from app.models.posts import Posts
from app.models.media_assets import MediaAssets
from app.constants.enums import MediaAssetKind
from app.models.user import Users
from sqlalchemy import func
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
            Plans.type == PlanStatus.PLAN,  # サブスクリプションプラン（type=2）
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

def create_plan(db: Session, plan_data) -> Plans:
    """
    プランを作成
    """
    db_plan = Plans(**plan_data)
    db.add(db_plan)
    db.flush()
    return db_plan

def get_user_plans(db: Session, user_id: UUID) -> List[PlanResponse]:
    """
    ユーザーのプラン一覧を取得
    """
    # priceテーブルと結合して金額情報を取得する
    plans = (
        db.query(Plans)
        .filter(
            Plans.creator_user_id == user_id,
            Plans.type == PlanStatus.PLAN,
            Plans.deleted_at.is_(None)
        )
    ).all()

    # レスポンス内容を整形する
    plans_response = []

    if plans:
        for plan in plans:
            plans_response.append(PlanResponse(
                id=plan.id,
                name=plan.name,
                description=plan.description,
                price=plan.price
            ))

    return plans_response

def get_plan_by_id(db: Session, plan_id: UUID) -> Plans:
    """
    プランをIDで取得
    """
    return db.query(Plans).filter(Plans.id == plan_id).first()