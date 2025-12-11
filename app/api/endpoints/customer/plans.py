from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.schemas.plan import (
    PlanCreateRequest,
    PlanUpdateRequest,
    PlanResponse,
    PlanListResponse,
    PlanPostsResponse,
    PlanPostResponse,
    PlanDetailResponse,
    PlanPostsPaginatedResponse,
    PlanSubscriberListResponse,
    PlanReorderRequest,
    CreatorPostsForPlanResponse,
)
from app.crud.plan_crud import (
    create_plan,
    delete_plan,
    update_plan,
    request_plan_deletion,
    get_user_plans,
    get_plan_detail,
    get_plan_posts_paginated,
    get_plan_subscribers_paginated,
    add_posts_to_plan,
    reorder_plans,
    get_creator_posts_for_plan,
    get_plan_by_id,
)
from app.crud.post_crud import get_posts_by_plan_id
from app.constants.enums import PlanStatus, PriceType
from app.crud.price_crud import create_price
from uuid import UUID
from typing import Optional
import os
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()
BASE_URL = os.getenv("CDN_BASE_URL")


@router.post("/create", response_model=PlanResponse)
def create_user_plan(
    plan_data: PlanCreateRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    プランを作成
    """
    try:
        # プランを登録
        plan_create_data = {
            "creator_user_id": current_user.id,
            "name": plan_data.name,
            "description": plan_data.description,
            "type": plan_data.type,
            "price": plan_data.price,
            "welcome_message": plan_data.welcome_message,
            "status": 1,  # アクティブ
        }
        plan = create_plan(db, plan_create_data, plan_data.post_ids)

        db.commit()
        db.refresh(plan)

        # 投稿数と加入者数を取得
        from app.models.plans import PostPlans
        from app.models.posts import Posts
        from app.constants.enums import PostStatus
        from sqlalchemy import func

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

        # 返却用に整形
        plan_response = PlanResponse(
            id=plan.id,
            name=plan.name,
            description=plan.description,
            price=plan.price,
            type=plan.type,
            display_order=plan.display_order,
            welcome_message=plan.welcome_message,
            post_count=post_count,
            subscriber_count=0,
        )

        return plan_response
    except Exception as e:
        logger.error("プラン作成エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list", response_model=PlanListResponse)
def get_plans(
    current_user: Users = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    ユーザーのプラン一覧を取得
    """
    try:
        plans_data = get_user_plans(db, current_user.id)
        plans = [PlanResponse(**plan) for plan in plans_data]

        return PlanListResponse(plans=plans)
    except Exception as e:
        logger.error("プラン取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{plan_id}/posts", response_model=PlanPostsResponse)
def get_plan_posts(
    plan_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    プランに紐づく投稿一覧を取得
    """
    try:
        posts_data = get_posts_by_plan_id(db, plan_id, current_user.id)

        posts = []
        for (
            post,
            profile_name,
            username,
            avatar_url,
            thumbnail_key,
            duration_sec,
            likes_count,
            comments_count,
            created_at,
        ) in posts_data:
            # 動画時間をフォーマット
            duration = None
            if duration_sec:
                minutes = int(duration_sec // 60)
                seconds = int(duration_sec % 60)
                duration = f"{minutes}:{seconds:02d}"

            post_response = PlanPostResponse(
                id=post.id,
                thumbnail_url=f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None,
                title=post.description or "",
                creator_avatar=f"{BASE_URL}/{avatar_url}" if avatar_url else None,
                creator_name=profile_name,
                creator_username=username,
                likes_count=likes_count or 0,
                comments_count=comments_count or 0,
                duration=duration,
                is_video=(post.post_type == 1),  # 1が動画
                created_at=created_at,
            )
            posts.append(post_response)

        return PlanPostsResponse(posts=posts)
    except Exception as e:
        logger.error("プラン投稿一覧取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{plan_id}", response_model=PlanDetailResponse)
def get_plan_detail_endpoint(
    plan_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    プラン詳細情報を取得
    """
    try:
        plan_detail = get_plan_detail(db, plan_id, current_user.id)

        if not plan_detail:
            raise HTTPException(status_code=404, detail="プランが見つかりません")

        return PlanDetailResponse(**plan_detail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("プラン詳細取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{plan_id}/posts-paginated", response_model=PlanPostsPaginatedResponse)
def get_plan_posts_paginated_endpoint(
    plan_id: UUID,
    page: int = 1,
    per_page: int = 20,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    プランに紐づく投稿一覧をページネーション付きで取得
    """
    try:
        if page < 1:
            raise HTTPException(
                status_code=400, detail="ページ番号は1以上である必要があります"
            )
        if per_page < 1 or per_page > 100:
            raise HTTPException(
                status_code=400,
                detail="1ページあたりの件数は1〜100である必要があります",
            )

        result = get_plan_posts_paginated(db, plan_id, current_user.id, page, per_page)

        # スキーマに合わせて変換
        posts = [PlanPostResponse(**post) for post in result["posts"]]

        return PlanPostsPaginatedResponse(
            posts=posts,
            total=result["total"],
            page=result["page"],
            per_page=result["per_page"],
            has_next=result["has_next"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("プラン投稿一覧取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/reorder")
def reorder_user_plans(
    request_data: PlanReorderRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    プランの並び順を更新
    """
    try:
        logger.info(f"受信データ: {request_data}")
        logger.info(f"plan_orders: {request_data.plan_orders}")
        logger.info(f"plan_orders型: {type(request_data.plan_orders)}")
        if request_data.plan_orders:
            logger.error(f"最初の要素: {request_data.plan_orders[0]}")
            logger.error(f"最初の要素の型: {type(request_data.plan_orders[0])}")
        reorder_plans(db, current_user.id, request_data.plan_orders)
        db.commit()
        return {"message": "プランの並び順を更新しました"}
    except Exception as e:
        logger.error(f"plan_orders型: {type(request_data.plan_orders)}")
        if request_data.plan_orders:
            logger.info(f"最初の要素: {request_data.plan_orders[0]}")
            logger.info(f"最初の要素の型: {type(request_data.plan_orders[0])}")

        reorder_plans(db, current_user.id, request_data.plan_orders)
        db.commit()

        return {"message": "プランの並び順を更新しました"}
    except Exception as e:
        logger.error("プラン並び替えエラーが発生しました", e)
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{plan_id}", response_model=PlanResponse)
def update_user_plan(
    plan_id: UUID,
    plan_data: PlanUpdateRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    プランを更新
    """
    try:
        # プランの所有者確認
        plan = get_plan_by_id(db, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="プランが見つかりません")
        if plan.creator_user_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="このプランを編集する権限がありません"
            )

        # 更新データを準備
        update_data = {}
        if plan_data.name is not None:
            update_data["name"] = plan_data.name
        if plan_data.description is not None:
            update_data["description"] = plan_data.description
        if plan_data.type is not None:
            update_data["type"] = plan_data.type
        if plan_data.welcome_message is not None:
            update_data["welcome_message"] = plan_data.welcome_message

        # プランを更新
        updated_plan = update_plan(db, plan_id, update_data)

        # 投稿を更新
        if plan_data.post_ids is not None:
            add_posts_to_plan(db, plan_id, plan_data.post_ids)

        db.commit()
        db.refresh(updated_plan)

        # 投稿数と加入者数を取得
        from app.models.plans import PostPlans
        from app.models.posts import Posts
        from app.constants.enums import PostStatus
        from sqlalchemy import func

        post_count = (
            db.query(func.count(PostPlans.post_id))
            .join(Posts, PostPlans.post_id == Posts.id)
            .filter(
                PostPlans.plan_id == updated_plan.id,
                Posts.deleted_at.is_(None),
                Posts.status == PostStatus.APPROVED,
            )
            .scalar()
            or 0
        )

        return PlanResponse(
            id=updated_plan.id,
            name=updated_plan.name,
            description=updated_plan.description,
            price=updated_plan.price,
            type=updated_plan.type,
            display_order=updated_plan.display_order,
            welcome_message=updated_plan.welcome_message,
            post_count=post_count,
            subscriber_count=0,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("プラン更新エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{plan_id}/delete-request")
def request_plan_delete(
    plan_id: UUID,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    プランの削除を申請
    """
    try:
        # プランの所有者確認
        plan = get_plan_by_id(db, plan_id)
        plan_detail = get_plan_detail(db, plan_id, current_user.id)
        if not plan or not plan_detail:
            raise HTTPException(status_code=404, detail="プランが見つかりません")
        if plan.creator_user_id != current_user.id:
            raise HTTPException(
                status_code=403, detail="このプランを削除する権限がありません"
            )
        if plan_detail["subscriptions_count"] > 0:
            request_plan_deletion(db, plan_id)
        elif plan_detail["subscriptions_count"] == 0:
            delete_plan(db, plan_id)
        # 削除申請
        db.commit()

        return {"message": "プランの削除を申請しました", "plan_id": str(plan_id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("プラン削除申請エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{plan_id}/subscribers", response_model=PlanSubscriberListResponse)
def get_plan_subscribers(
    plan_id: UUID,
    page: int = 1,
    per_page: int = 20,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    プランの加入者一覧を取得
    """
    try:
        # プランの所有者確認
        plan = get_plan_by_id(db, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="プランが見つかりません")
        if plan.creator_user_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="このプランの加入者一覧を閲覧する権限がありません",
            )

        result = get_plan_subscribers_paginated(db, plan_id, page, per_page)

        return PlanSubscriberListResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("加入者一覧取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/posts/for-plan", response_model=CreatorPostsForPlanResponse)
def get_posts_for_plan(
    plan_id: Optional[UUID] = None,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    クリエイターの投稿一覧を取得（プラン作成・編集用）
    """
    try:
        posts = get_creator_posts_for_plan(db, current_user.id, plan_id)
        return CreatorPostsForPlanResponse(posts=posts)
    except Exception as e:
        logger.error("投稿一覧取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))
