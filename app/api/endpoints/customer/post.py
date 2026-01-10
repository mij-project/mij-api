import math
from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from app.crud.time_sale_crud import (
    check_exists_price_time_sale_in_period_by_post_id,
    create_price_time_sale_by_post_id,
    delete_price_time_sale_by_id,
    get_price_time_sale_by_post_id,
    get_active_price_timesale,
)
from app.crud.payments_crud import get_payment_status_by_price_id
from app.db.base import get_db
from app.deps.auth import get_current_user, get_current_user_optional
from app.constants.enums import PostStatus
from app.models.user import Users
from app.schemas.post import (
    PostCreateRequest,
    PostResponse,
    NewArrivalsResponse,
    PaginatedNewArrivalsResponse,
    PostUpdateRequest,
    PostOGPResponse,
)
from app.constants.enums import PostVisibility, PostType, PriceType, MediaAssetKind
from app.crud.post_crud import (
    create_post,
    get_post_detail_by_id,
    mark_post_as_deleted,
    update_post,
    get_post_ogp_data,
)
from app.crud.price_crud import create_price
from app.models.prices import Prices
from app.crud.post_plans_crud import create_post_plan, delete_plan_by_post_id
from app.crud.tags_crud import exit_tag, create_tag
from app.crud.post_tags_crud import create_post_tag, delete_post_tags_by_post_id
from app.crud.post_categories_crud import (
    create_post_category,
    delete_post_categories_by_post_id,
)
from app.crud.post_crud import get_recent_posts
from app.models.tags import Tags
import os
from os import getenv
from datetime import datetime, timezone
from app.api.commons.utils import get_video_duration
from app.core.logger import Logger
from app.schemas.post_price_timesale import (
    PaginatedPriceTimeSaleResponse,
    PriceTimeSaleCreateRequest,
    PriceTimeSaleResponse,
)
from app.services.slack.slack import SlackService
import time

slack_alert = SlackService.initialize()
logger = Logger.get_logger()
router = APIRouter()

# PostTypeの文字列からenumへのマッピングを定義
POST_TYPE_MAPPING = {
    "video": PostType.VIDEO,
    "image": PostType.IMAGE,
}


BASE_URL = getenv("CDN_BASE_URL")
MEDIA_CDN_URL = os.getenv("MEDIA_CDN_URL")
CDN_BASE_URL = os.getenv("CDN_BASE_URL")


@router.post("/create", response_model=PostResponse)
async def create_post_endpoint(
    post_create: PostCreateRequest,
    user=Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """投稿を作成する"""
    try:
        # 可視性を判定
        visibility = _determine_visibility(post_create.single, post_create.plan)

        # 関連オブジェクトを初期化
        price = None
        plan_posts = []
        category_posts = []
        tag_posts = []

        # 投稿を作成
        post = _create_post(db, post_create, user.id, visibility)

        # 単品販売の場合、価格を登録
        if post_create.single:
            price = _create_price(db, post.id, post_create.price)

        # プランの場合、プランを登録
        if post_create.plan:
            plan_posts = _create_plan(db, post.id, post_create.plan_ids)

        # カテゴリを投稿に紐づけ
        if post_create.category_ids:
            category_posts = _create_post_categories(
                db, post.id, post_create.category_ids
            )

        # タグを投稿に紐づけ
        if post_create.tags:
            tag_posts = _create_post_tag(db, post.id, post_create.tags)

        # データベースをコミット
        db.commit()

        # オブジェクトをリフレッシュ
        _refresh_related_objects(db, post, price, plan_posts, category_posts, tag_posts)

        slack_alert._alert_post_creation(user.profile_name)

        return post

    except Exception as e:
        db.rollback()
        logger.error("投稿作成エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/update")
async def update_post_endpoint(
    request_data: PostUpdateRequest,
    current_user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    """投稿を更新する"""
    try:
        # 投稿を更新
        # 可視性を判定
        visibility = _determine_visibility(request_data.single, request_data.plan)

        # 関連オブジェクトを初期化
        price = None
        plan_posts = []
        category_posts = []
        tag_posts = []

        # 投稿を更新
        post = _update_post(db, request_data, current_user.id, visibility)

        # 単品販売の場合、価格をデリートインサート
        if request_data.single:
            # 決済処理でロックがかかっている可能性があるので、ロックをかけてから削除・挿入する
            # 10回リトライする
            _delete_and_insert_price(db, request_data.post_id, request_data.price)

        # プランの場合、プランをデリートインサート
        if request_data.plan:
            delete_plan_by_post_id(db, request_data.post_id)
            plan_posts = _create_plan(db, request_data.post_id, request_data.plan_ids)

        # カテゴリをデリートインサート
        if request_data.category_ids:
            delete_post_categories_by_post_id(db, request_data.post_id)
            category_posts = _create_post_categories(
                db, request_data.post_id, request_data.category_ids
            )

        # タグをデリートインサート
        if request_data.tags:
            delete_post_tags_by_post_id(db, request_data.post_id)
            tag_posts = _create_post_tag(db, request_data.post_id, request_data.tags)

        # データベースをコミット
        db.commit()

        # オブジェクトをリフレッシュ
        _refresh_related_objects(db, post, price, plan_posts, category_posts, tag_posts)

        slack_alert._alert_post_update(current_user.profile_name)

        return post
    except Exception as e:
        db.rollback()
        logger.error("投稿更新エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detail")
async def get_post_detail(
    post_id: str = Query(..., description="投稿ID"),
    user=Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    try:
        # CRUD関数を使用して投稿詳細を取得
        user_id = user.id if user else None

        post_data = get_post_detail_by_id(db, post_id, user_id)

        if not post_data:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        # クリエイター情報を整形
        creator_info = _format_creator_info(
            post_data["creator"], post_data["creator_profile"]
        )

        # 投稿者自身かどうかを判定
        is_own_post = user_id and str(post_data["post"].creator_user_id) == str(user_id)

        # メディア情報を整形
        media_info, thumbnail_key, main_duration = _format_media_info(
            post_data["media_assets"],
            post_data["is_entitlement"],
            post_data["price"],
            is_own_post,
        )
        # カテゴリ情報を整形
        categories_data = _format_categories_info(post_data["categories"])

        # 販売情報を整形
        sale_info = _format_sale_info(
            post_data["price"], post_data["plans"], post_data["plan_timesale_map"]
        )

        # salesinfoにprice_idがある場合、振込待ちかの判定
        # is_pending_payment = False
        # if post_data["price"].id:
        #     is_pending_payment = bool(get_payment_status_by_price_id(db, str(post_data["price"].id)))

        # Schedule and Expiration Information
        schedule_info, expiration_info = (
            post_data["post"].scheduled_at,
            post_data["post"].expiration_at,
        )
        now = datetime.now(timezone.utc)
        if schedule_info and schedule_info.replace(tzinfo=timezone.utc) > now:
            is_scheduled = True
        else:
            is_scheduled = False
        if expiration_info and expiration_info.replace(tzinfo=timezone.utc) < now:
            is_expired = True
        else:
            is_expired = False
        # 投稿詳細を整形
        post_detail = {
            "id": str(post_data["post"].id),
            "post_type": post_data["post"].post_type,
            "description": post_data["post"].description,
            "thumbnail_key": thumbnail_key,
            "creator": creator_info,
            "categories": categories_data,
            "media_info": media_info,
            "sale_info": sale_info,
            "post_main_duration": main_duration,
            "is_purchased": post_data["is_entitlement"]
            or is_own_post,  # 購入済み or 自分の投稿
            "is_scheduled": is_scheduled,
            "is_expired": is_expired,
            "is_pending_payment": is_pending_payment,
        }

        return post_detail

    except HTTPException:
        raise
    except Exception as e:
        logger.error("投稿詳細取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/new-arrivals", response_model=PaginatedNewArrivalsResponse)
async def get_new_arrivals(
    page: int = Query(1, ge=1, description="ページ番号（1から開始）"),
    per_page: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    db: Session = Depends(get_db),
):
    try:
        # ページ番号からオフセットを計算
        # offset = (page - 1) * per_page

        # 次のページがあるか確認するため、1件多く取得
        recent_posts = get_recent_posts(db, limit=per_page + 1)

        # has_nextの判定
        has_next = len(recent_posts) > per_page

        # 実際に返すのはper_page件まで
        posts_to_return = recent_posts[:per_page]

        posts = [
            NewArrivalsResponse(
                id=str(post.Posts.id),
                description=post.Posts.description,
                thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}"
                if post.thumbnail_key
                else None,
                creator_name=post.profile_name,
                username=post.username,
                creator_avatar_url=f"{BASE_URL}/{post.avatar_url}"
                if post.avatar_url
                else None,
                duration=get_video_duration(post.duration_sec)
                if post.duration_sec
                else None,
                likes_count=post.likes_count or 0,
                is_time_sale=post.Posts.is_time_sale,
            )
            for post in posts_to_return
        ]

        return PaginatedNewArrivalsResponse(
            posts=posts,
            page=page,
            per_page=per_page,
            has_next=has_next,
            has_previous=page > 1,
        )
    except Exception as e:
        logger.error("新着投稿取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{post_id}/ogp-image", response_model=PostOGPResponse)
async def get_post_ogp_image(post_id: str, db: Session = Depends(get_db)):
    """投稿のOGP情報を取得する（Lambda@Edge用）"""
    try:
        # OGP情報を取得（投稿詳細 + クリエイター情報 + OGP画像）
        ogp_data = get_post_ogp_data(db, post_id)

        if not ogp_data:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        return ogp_data

    except HTTPException:
        raise
    except Exception as e:
        logger.error("OGP画像URL取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{post_id}/time-sale/{price_id}")
async def get_post_time_sale(post_id: str, price_id: str, db: Session = Depends(get_db)):
    """投稿のタイムセール情報を取得する"""
    time_sale = get_active_price_timesale(db, post_id, price_id)
    if not time_sale:
        return False
    return time_sale["is_active"]

# utils
def _determine_visibility(single: bool, plan: bool) -> int:
    """投稿の可視性を判定する"""
    if single and plan:
        return PostVisibility.BOTH
    elif single:
        return PostVisibility.SINGLE
    elif plan:
        return PostVisibility.PLAN
    else:
        return PostVisibility.SINGLE  # デフォルト


def _create_post(db: Session, post_data: dict, user_id: str, visibility: int):
    """投稿を作成する"""
    post_data = {
        "creator_user_id": user_id,
        "description": post_data.description,
        "scheduled_at": post_data.formattedScheduledDateTime
        if post_data.scheduled
        else None,
        "expiration_at": post_data.expirationDate if post_data.expiration else None,
        "visibility": visibility,
        "post_type": POST_TYPE_MAPPING.get(post_data.post_type),
    }
    return create_post(db, post_data)


def _create_post_categories(db: Session, post_id: str, category_ids: list):
    """投稿にカテゴリを紐づける"""
    category_posts = []
    for category_id in category_ids:
        category_data = {
            "post_id": post_id,
            "category_id": category_id,
        }
        category_post = create_post_category(db, category_data)
        category_posts.append(category_post)
    return category_posts


def _create_post_tag(db: Session, post_id: str, tag_name: str):
    """投稿にタグを紐づける"""
    # タグが存在するか確認
    existing_tag = exit_tag(db, tag_name)

    if not existing_tag:
        tag_data = {
            "slug": tag_name,
            "name": tag_name,
        }
        tag = create_tag(db, tag_data)
    else:
        tag = db.query(Tags).filter(Tags.name == tag_name).first()

    # タグと投稿の中間テーブルに登録
    post_tag_data = {
        "post_id": post_id,
        "tag_id": tag.id,
    }
    return create_post_tag(db, post_tag_data)


def _update_post(
    db: Session, request_data: PostUpdateRequest, user_id: str, visibility: int
):
    """投稿を更新する"""
    post_data = {
        "id": request_data.post_id,
        "creator_user_id": user_id,
        "description": request_data.description,
        "scheduled_at": request_data.formattedScheduledDateTime
        if request_data.scheduled
        else None,
        "expiration_at": request_data.expirationDate
        if request_data.expiration
        else None,
        "visibility": visibility,
        "status": request_data.status if request_data.status else PostStatus.RESUBMIT,
        "reject_comments": "",
    }
    return update_post(db, post_data)


def _delete_and_insert_price(db: Session, post_id: str, price: int):
    """投稿に価格をデリートインサートする"""
    for retry_count in range(10):
        try:
            # 既存の価格レコードに対してロックをかける（存在する場合）
            existing_prices = (
                db.query(Prices)
                .filter(Prices.post_id == post_id)
                .with_for_update()
                .all()
            )

            # 既存の価格を削除
            if existing_prices:
                for existing_price in existing_prices:
                    db.delete(existing_price)
                db.flush()  # 削除をフラッシュ

            # 新しい価格を挿入
            price = _create_price(db, post_id, price)
            break  # 成功したらループを抜ける
        except Exception as e:
            db.rollback()  # エラー時はロールバック
            logger.warning(
                f"価格デリートインサートエラー（リトライ {retry_count + 1}/10）: {e}"
            )
            if retry_count < 9:  # 最後のリトライでない場合のみ待機
                time.sleep(0.5)  # 500ms待機
            else:
                logger.error("価格デリートインサートが10回失敗しました", e)
                raise


def _refresh_related_objects(
    db: Session, post, price=None, plan_posts=None, category_posts=None, tag_posts=None
):
    """関連オブジェクトをリフレッシュする"""
    db.refresh(post)

    if price:
        db.refresh(price)

    if plan_posts:
        for plan_post in plan_posts:
            db.refresh(plan_post)

    if category_posts:
        for category_post in category_posts:
            db.refresh(category_post)

    if tag_posts:
        for tag_post in tag_posts:
            db.refresh(tag_post)


def _create_price(db: Session, post_id: str, price: int):
    """投稿に価格を紐づける"""

    price_data = {
        "post_id": post_id,
        "type": PriceType.SINGLE,
        "currency": "JPY",
        "is_active": True,
        "price": price,
        "starts_at": datetime.now(timezone.utc),
    }
    return create_price(db, price_data)


def _create_plan(db: Session, post_id: str, plan_ids: list):
    """投稿にプランを紐づける"""
    plan_post = []
    for plan_id in plan_ids:
        plan_post_data = {
            "post_id": post_id,
            "plan_id": plan_id,
        }
        plan_post.append(create_post_plan(db, plan_post_data))
    return plan_post


def _format_media_info(
    media_assets: list, is_entitlement: bool, price: dict, is_own_post: bool = False
):
    """メディア情報を整形する。priceは今後の判定用に受け取る。"""
    # 投稿者自身、または視聴権限がある場合はMAIN_VIDEOを表示
    should_show_main = is_own_post or is_entitlement
    set_media_kind = (
        MediaAssetKind.MAIN_VIDEO if should_show_main else MediaAssetKind.SAMPLE_VIDEO
    )
    set_file_name = "_1080w.webp" if should_show_main else "_blurred.webp"

    # 単品販売で価格が0の場合、画像のみブラーなしで表示（動画は通常通りis_entitlementで判定）
    free_image_flg = True if price and price.price == 0 else False

    media_info = []
    thumbnail_key = None
    main_duration = None
    for media_asset in media_assets:
        if media_asset.kind == MediaAssetKind.THUMBNAIL:
            thumbnail_key = f"{CDN_BASE_URL}/{media_asset.storage_key}"
        elif media_asset.kind == MediaAssetKind.IMAGES:
            # 画像の場合: 0円ならブラーなし、それ以外は通常のset_file_nameを使用
            image_file_name = "_1080w.webp" if free_image_flg else set_file_name
            media_info.append(
                {
                    "kind": media_asset.kind,
                    "duration": media_asset.duration_sec,
                    "media_assets_id": media_asset.id,
                    "orientation": media_asset.orientation,
                    "post_id": media_asset.post_id,
                    "storage_key": f"{MEDIA_CDN_URL}/{media_asset.storage_key}{image_file_name}",
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
    for media_asset in media_assets:
        if media_asset.kind == MediaAssetKind.MAIN_VIDEO:
            main_duration = media_asset.duration_sec
            break

    return media_info, thumbnail_key, main_duration


def _format_creator_info(creator: dict, creator_profile: dict):
    """クリエイター情報を整形する"""
    return {
        "user_id": str(creator.id),
        "username": creator_profile.username if creator_profile else creator.email,
        "official": creator.offical_flg if hasattr(creator, "offical_flg") else False,
        "profile_name": creator.profile_name if creator_profile else creator.email,
        "avatar": f"{BASE_URL}/{creator_profile.avatar_url}"
        if creator_profile.avatar_url
        else None,
    }


def _format_categories_info(categories: list):
    """カテゴリ情報を整形する"""
    return [
        {"id": str(category.id), "name": category.name, "slug": category.slug}
        for category in categories
    ]


def _format_sale_info(
    price: dict | None, plans: list | None, plan_timesale_map: dict | None
):
    """販売情報を整形する"""
    temp_plans = []
    for plan in plans:
        plan_id = str(plan["id"])
        tmp_plan_dict = {
            "id": str(plan["id"]) if plan and "id" in plan else None,
            "name": plan["name"] if plan and "name" in plan else None,
            "description": plan.get("description") if plan else None,
            "price": plan.get("price") if plan else None,
            "type": plan.get("type") if plan else None,
                "open_dm_flg": plan.get("open_dm_flg") if plan else None,
            "post_count": plan.get("post_count") if plan else None,
            "plan_post": [
                {
                    "description": post["description"],
                    "thumbnail_url": f"{CDN_BASE_URL}/{post['thumbnail_url']}",
                }
                for post in plan.get("plan_post", [])
            ]
            if plan and "plan_post" in plan
            else [],
        }
        is_time_sale_active = False
        time_sale_price = None
        sale_percentage = None
        end_date = None
        if plan_id in plan_timesale_map:
            if plan_timesale_map[plan_id]["is_active"] and (
                not plan_timesale_map[plan_id]["is_expired"]
            ):
                is_time_sale_active = True
                time_sale_price = int(plan["price"]) - math.ceil(
                    int(plan["price"])
                    * plan_timesale_map[plan_id]["sale_percentage"]
                    / 100
                )
                sale_percentage = plan_timesale_map[plan_id]["sale_percentage"]
                end_date = plan_timesale_map[plan_id]["end_date"]
        tmp_plan_dict["is_time_sale_active"] = is_time_sale_active
        tmp_plan_dict["time_sale_price"] = time_sale_price
        tmp_plan_dict["sale_percentage"] = sale_percentage
        tmp_plan_dict["end_date"] = end_date
        temp_plans.append(tmp_plan_dict)

    return {
        "price": {
            "id": str(price.id) if price else None,
            "price": price.price if price else None,
            "is_time_sale_active": price.is_time_sale_active if price else False,
            "time_sale_price": price.time_sale_price if price else None,
            "sale_percentage": price.sale_percentage if price else None,
            "end_date": price.end_date if price else None,
        },
        "plans": temp_plans,
    }


@router.delete("/{post_id}")
async def delete_post(
    post_id: str,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """投稿を削除する"""
    try:
        mark_post_as_deleted(db, post_id, current_user.id)
        return {"message": "投稿が削除されました"}
    except Exception as e:
        db.rollback()
        logger.error("投稿削除エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{post_id}/price-time-sale")
async def get_price_time_sale(
    post_id: str,
    page: int = Query(1, ge=1, description="ページ番号（1から開始）"),
    per_page: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """投稿の価格時間販売情報を取得する"""
    rows, total = get_price_time_sale_by_post_id(db, post_id, page, per_page)
    total_pages = math.ceil((total - 1) / per_page)
    time_sales = []
    for row in rows:
        time_sales.append(
            PriceTimeSaleResponse(
                id=str(row.TimeSale.id),
                post_id=str(row.TimeSale.post_id),
                plan_id=str(row.TimeSale.plan_id) if row.TimeSale.plan_id else None,
                price_id=str(row.TimeSale.price_id) if row.TimeSale.price_id else None,
                start_date=row.TimeSale.start_date if row.TimeSale.start_date else None,
                end_date=row.TimeSale.end_date if row.TimeSale.end_date else None,
                sale_percentage=row.TimeSale.sale_percentage,
                max_purchase_count=row.TimeSale.max_purchase_count
                if row.TimeSale.max_purchase_count
                else None,
                purchase_count=row.purchase_count,
                is_active=row.is_active,
                is_expired=row.is_expired,
                created_at=row.TimeSale.created_at if row.TimeSale.created_at else None,
            )
        )
    return PaginatedPriceTimeSaleResponse(
        time_sales=time_sales,
        total=total,
        total_pages=total_pages,
        page=page,
        limit=per_page,
        has_next=page < total_pages,
    )


@router.post("/{post_id}/create-price-time-sale")
async def create_price_time_sale(
    post_id: str,
    payload: PriceTimeSaleCreateRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """価格時間販売情報を作成する"""
    if payload.start_date and payload.end_date:
        if check_exists_price_time_sale_in_period_by_post_id(
            db, post_id, payload.start_date, payload.end_date
        ):
            raise HTTPException(
                status_code=400, detail="Price time sale already exists"
            )

    time_sale = create_price_time_sale_by_post_id(db, post_id, payload, current_user)
    if not time_sale:
        raise HTTPException(status_code=500, detail="Can not create price time sale")
    return {"message": "ok"}

@router.delete("/delete-price-time-sale/{time_sale_id}")
async def delete_price_time_sale(
    time_sale_id: str,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user),
):
    """価格時間販売情報を削除する"""
    success = delete_price_time_sale_by_id(db, time_sale_id, current_user.id)
    if not success:
        raise HTTPException(status_code=500, detail="Can not delete price time sale")
    return {"message": "ok"}
