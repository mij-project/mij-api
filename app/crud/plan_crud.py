from sqlalchemy.orm import Session
from app.models.plans import Plans
from app.models.subscriptions import Subscriptions
from app.models.prices import Prices
from uuid import UUID
from typing import List
from app.schemas.plan import PlanCreateRequest, PlanResponse, SubscribedPlanResponse
from app.constants.enums import PlanStatus
from datetime import datetime
from app.models.purchases import Purchases
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

    # 購入したサブスクリプションプラン（type=2）を取得
    subscribed_purchases = (
        db.query(Purchases)
        .join(Plans, Purchases.plan_id == Plans.id)
        .join(Prices, Plans.id == Prices.plan_id)
        .filter(
            Purchases.user_id == user_id,
            Plans.type == PlanStatus.PLAN,  # サブスクリプションプラン（type=2）
            Plans.deleted_at.is_(None),  # 削除されていないプラン
            Purchases.deleted_at.is_(None)  # 削除されていない購入
        )
        .all()
    )

    subscribed_plan_count = len(subscribed_purchases)
    subscribed_total_price = 0
    subscribed_plan_names = []
    subscribed_plan_details = []

    # 加入中のプランの詳細情報を取得
    for purchase in subscribed_purchases:
        price = (
            db.query(
                Prices
            )
            .filter(Prices.plan_id == purchase.plan_id)
            .first()
        )

        # クリエイター情報を取得
        creator_profile = (
            db.query(
                Profiles.avatar_url,
                Profiles.username,
                Users.profile_name,
            )
            .join(Users, Profiles.user_id == Users.id)
            .filter(
                Users.id == purchase.plan.creator_user_id,
                Profiles.user_id == purchase.plan.creator_user_id,
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
                PostPlans.plan_id == purchase.plan_id,
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
                PostPlans.plan_id == purchase.plan_id,
                MediaAssets.kind == MediaAssetKind.THUMBNAIL,
                Posts.deleted_at.is_(None),
                Posts.status == PostStatus.APPROVED
            )
            .order_by(Posts.created_at.desc())
            .limit(4)
            .all()
        )

        thumbnail_keys = [thumb.storage_key for thumb in thumbnails]

        if price:
            subscribed_total_price += price.price
            subscribed_plan_names.append(purchase.plan.name)

            # 詳細情報を追加
            subscribed_plan_details.append({
                "purchase_id": str(purchase.id),
                "plan_id": str(purchase.plan.id),
                "plan_name": purchase.plan.name,
                "plan_description": purchase.plan.description,
                "price": price.price,
                "purchase_created_at": purchase.created_at,
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