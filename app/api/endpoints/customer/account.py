import jwt
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Response, background
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Dict
from app.constants.enums import PostType
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.schemas.account import (
    AccountEmailSettingRequest,
    Kind,
    AccountInfoResponse,
    AccountUpdateRequest,
    AccountUpdateResponse,
    AvatarPresignRequest,
    AccountPresignResponse,
    AccountPostStatusResponse,
    AccountPostResponse,
    AccountPostDetailResponse,
    AccountPostUpdateRequest,
    AccountPostUpdateResponse,
    LikedPostResponse,
    ProfileInfo,
    ProfileEditInfo,
    SocialInfo,
    PostsInfo,
    SalesInfo,
    PlanInfo,
    PlansSubscribedInfo,
    PostCardResponse,
    BookmarkedPostsResponse,
    LikedPostsListResponse,
    BoughtPostsResponse,
)
from app.schemas.profile_image import (
    ProfileImageSubmissionCreate,
    ProfileImageSubmissionResponse,
    ProfileImageStatusResponse
)
from app.schemas.commons import UploadItem, PresignResponseItem
from app.crud.followes_crud import get_follower_count
from app.crud.post_crud import (
    get_total_likes_by_user_id,
    get_posts_count_by_user_id,
    get_post_status_by_user_id,
    get_liked_posts_by_user_id,
    get_bookmarked_posts_by_user_id,
    get_liked_posts_list_by_user_id,
    get_bought_posts_by_user_id,
    get_post_detail_for_creator,
    update_post_by_creator
)
from app.crud.post_categries import get_post_categories
from app.crud.sales_crud import get_total_sales
from app.crud.plan_crud import get_plan_by_user_id
from app.crud.user_crud import check_profile_name_exists, update_user
from app.crud.profile_crud import get_profile_by_user_id, get_profile_info_by_user_id, get_profile_edit_info_by_user_id, update_profile, exist_profile_by_username
from app.crud import profile_image_crud
from app.services.email.send_email import send_email_verification
from app.services.s3.keygen import account_asset_key
from app.services.s3.presign import presign_put_public
from app.crud.post_crud import get_post_by_id
from app.crud.post_plans_crud import get_post_plans 
from uuid import UUID
from app.api.commons.utils import resolve_media_asset_storage_key
import os
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()
BASE_URL = os.getenv("CDN_BASE_URL")

TWITTER_URL = "https://x.com"
INSTAGRAM_URL = "https://www.instagram.com"
YOUTUBE_URL = "https://www.youtube.com"
TIKTOK_URL = "https://www.tiktok.com/"

@router.get("/info", response_model=AccountInfoResponse)
def get_account_info(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    アカウント情報を取得

    Args:
        current_user (Users): 現在のユーザー
        db (Session): データベースセッション

    Returns:
        AccountInfoResponse: アカウント情報

    Raises:
        HTTPException: エラーが発生した場合
    """
    try:

        # プロフィール情報
        profile_info_data = get_profile_info_by_user_id(db, current_user.id)
        profile_info = ProfileInfo(
            profile_name=profile_info_data["profile_name"] or "",
            username=profile_info_data["username"] or "",
            avatar_url=f"{BASE_URL}/{profile_info_data['avatar_url']}" if profile_info_data["avatar_url"] else None,
            cover_url=f"{BASE_URL}/{profile_info_data['cover_url']}" if profile_info_data["cover_url"] else None,
        )

        # いいね数とタプルをLikedPostResponseオブジェクトに変換
        total_likes = get_total_likes_by_user_id(db, current_user.id)
        liked_posts_data = get_liked_posts_by_user_id(db, current_user.id)
        liked_posts = []
        for post_tuple in liked_posts_data:
            post, profile_name, username, avatar_url, thumbnail_key, duration_sec, created_at = post_tuple
            liked_post = LikedPostResponse(
                id=post.id,
                description=post.description,
                creator_user_id=post.creator_user_id,
                profile_name=profile_name,
                username=username,
                avatar_url=f"{BASE_URL}/{avatar_url}" if avatar_url else None,
                thumbnail_key=f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None,
                duration_sec=duration_sec,
                created_at=created_at,
                updated_at=post.updated_at
            )
            liked_posts.append(liked_post)
        
        follower_data = get_follower_count(db, current_user.id)
        social_info = SocialInfo(
            followers_count=follower_data["followers_count"] if follower_data else 0,
            following_count=follower_data["following_count"] if follower_data else 0,
            total_likes=total_likes or 0,
            liked_posts=liked_posts,
        )

        # 投稿数
        posts_data = get_posts_count_by_user_id(db, current_user.id)
        posts_info = PostsInfo(
            pending_posts_count=posts_data["peding_posts_count"] if posts_data else 0,
            rejected_posts_count=posts_data["rejected_posts_count"] if posts_data else 0,
            unpublished_posts_count=posts_data["unpublished_posts_count"] if posts_data else 0,
            deleted_posts_count=posts_data["deleted_posts_count"] if posts_data else 0,
            approved_posts_count=posts_data["approved_posts_count"] if posts_data else 0,
            reserved_posts_count=posts_data["reserved_posts_count"] if posts_data else 0,
        )
        
        # 売上
        total_sales = get_total_sales(db, current_user.id)
        sales_info = SalesInfo(
            total_sales=total_sales or 0,
        )

        # プラン情報
        plan_data = get_plan_by_user_id(db, current_user.id)
        # 単品購入データ
        single_purchases_count = 0
        single_purchases_data = []

        # subscribed_plan_detailsのURLを構築
        subscribed_plan_details = []
        for plan in plan_data.get("subscribed_plan_details", []):
            subscribed_plan_details.append({
                **plan,
                "creator_avatar_url": f"{BASE_URL}/{plan['creator_avatar_url']}" if plan.get('creator_avatar_url') else None,
                "thumbnail_keys": [f"{BASE_URL}/{key}" for key in plan.get('thumbnail_keys', [])]
            })

        plan_info = PlanInfo(
            plan_count=plan_data["plan_count"] if plan_data else 0,
            total_price=plan_data["total_price"] if plan_data else 0,
            subscribed_plan_count=plan_data["subscribed_plan_count"] if plan_data else 0,
            subscribed_total_price=plan_data["subscribed_total_price"] if plan_data else 0,
            subscribed_plan_details=subscribed_plan_details,
            single_purchases_count=single_purchases_count if single_purchases_count else 0,
            single_purchases_data=single_purchases_data if single_purchases_data else [],
        )

        return AccountInfoResponse(
            profile_info=profile_info,
            social_info=social_info,
            posts_info=posts_info,
            sales_info=sales_info,
            plan_info=plan_info,
        )
    except Exception as e:
        logger.error("アカウント情報取得エラーが発生しました", e)
        # エラー時はデフォルト値で返す
        return AccountInfoResponse(
            profile_info=ProfileInfo(
                profile_name=current_user.profile_name or "",
                username="",
                avatar_url=None,
                cover_url=None,
            ),
            social_info=SocialInfo(
                followers_count=0,
                following_count=0,
                total_likes=0,
                liked_posts=[],
            ),
            posts_info=PostsInfo(
                pending_posts_count=0,
                rejected_posts_count=0,
                unpublished_posts_count=0,
                deleted_posts_count=0,
                approved_posts_count=0,
                reserved_posts_count=0,
            ),
            sales_info=SalesInfo(
                total_sales=0,
            ),
            plan_info=PlanInfo(
                plan_count=0,
                total_price=0,
                subscribed_plan_count=0,
                subscribed_total_price=0,
                subscribed_plan_names=[],
                subscribed_plan_details=[],
                single_purchases_count=0,
                single_purchases_data=[],
            ),
        )

@router.get("/profile", response_model=ProfileEditInfo)
def get_profile_edit_info(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    プロフィール編集用の情報を取得（軽量版）

    Args:
        current_user (Users): 現在のユーザー
        db (Session): データベースセッション

    Returns:
        ProfileEditInfo: プロフィール編集用の情報

    Raises:
        HTTPException: エラーが発生した場合
    """
    try:
        profile_data = get_profile_edit_info_by_user_id(db, current_user.id)

        if not profile_data:
            raise HTTPException(status_code=404, detail="プロフィール情報が見つかりませんでした")

        return ProfileEditInfo(
            profile_name=profile_data["profile_name"] or "",
            username=profile_data["username"] or "",
            avatar_url=f"{BASE_URL}/{profile_data['avatar_url']}" if profile_data.get("avatar_url") else None,
            cover_url=f"{BASE_URL}/{profile_data['cover_url']}" if profile_data.get("cover_url") else None,
            bio=profile_data.get("bio"),
            links=profile_data.get("links", {})
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("プロフィール編集情報取得エラー:", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/update", response_model=AccountUpdateResponse)
def update_account_info(
    update_data: AccountUpdateRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    アカウント情報を更新

    Args:
        update_data (AccountUpdateRequest): 更新するアカウント情報
        current_user (Users): 現在のユーザー
        db (Session): データベースセッション

    Returns:
        AccountUpdateResponse: アカウント情報更新のレスポンス

    Raises:
        HTTPException: エラーが発生した場合
    """
    try:
        # 現在のプロフィール情報を取得
        current_profile = get_profile_by_user_id(db, current_user.id)

        # 氏名の変更チェックと重複確認
        name_changed = update_data.name and update_data.name != current_user.profile_name
        if name_changed:
            logger.info(f"氏名変更を検出: {current_user.profile_name} -> {update_data.name}")
            if check_profile_name_exists(db, update_data.name):
                logger.warning(f"氏名の重複エラー: {update_data.name}")
                return Response(content="このユーザ名は既に使用されています", status_code=400)

        # ユーザーネームの変更チェックと重複確認
        username_changed = (update_data.username and current_profile
                           and update_data.username != current_profile.username)
        if username_changed:
            logger.info(f"ユーザーネーム変更を検出: {current_profile.username} -> {update_data.username}")
            if exist_profile_by_username(db, update_data.username):
                logger.warning(f"ユーザーネームの重複エラー: {update_data.username}")
                return Response(content="このユーザーネームは既に使用されています", status_code=400)

        # ユーザー情報の更新（氏名が変更された場合のみ）
        if name_changed:
            user = update_user(db, current_user.id, update_data.name)

        links = update_data.links if update_data.links else {}
        instagram = links.get("instagram", "")
        instagram_link = f"{INSTAGRAM_URL}/{instagram.replace('@', '')}" if instagram else ""
        tiktok = links.get("tiktok", "")
        if tiktok and tiktok.startswith("@"):
            tiktok_link = f"{TIKTOK_URL}/{tiktok}"
        elif tiktok and not tiktok.startswith("@"):
            tiktok_link = f"{TIKTOK_URL}/@{tiktok}"
        else:
            tiktok_link = ""
        twitter = links.get("twitter", "")
        twitter_link = f"{TWITTER_URL}/{twitter.replace('@', '')}" if twitter else ""
        youtube = links.get("youtube", "")
        if youtube and youtube.startswith("@"):
            youtube_link = f"{YOUTUBE_URL}/{youtube}"
        elif youtube and not youtube.startswith("@"):
            youtube_link = f"{YOUTUBE_URL}/@{youtube}"
        else:
            youtube_link = ""
        website = links.get("website", "")
        website2 = links.get("website2", "")

        update_links = {
            "instagram": instagram,
            "instagram_link": instagram_link,
            "tiktok": tiktok,
            "tiktok_link": tiktok_link,
            "twitter": twitter,
            "twitter_link": twitter_link,
            "youtube": youtube,
            "youtube_link": youtube_link,
            "website": website,
            "website2": website2,
        }

        update_data.links = update_links

        # プロフィール情報の更新（username、description、links、avatar_url、cover_urlのいずれかがある場合）
        if any([update_data.username, update_data.description, update_data.links,
                update_data.avatar_url, update_data.cover_url]):
            profile = update_profile(db, current_user.id, update_data)

        db.commit()

        # 更新されたオブジェクトのリフレッシュ
        if 'user' in locals():
            db.refresh(user)
        if 'profile' in locals():
            db.refresh(profile)

        return AccountUpdateResponse(
            message="アカウント情報が正常に更新されました",
            success=True
        )

    except Exception as e:
        logger.error("アカウント情報更新エラーが発生しました", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/presign-upload")
def presign_upload(
    request: AvatarPresignRequest,
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    アバターのアップロードURLを生成
    """
    try:

        allowed_kinds =  {"avatar","cover"}

        seen = set()
        for f in request.files:
            if f.kind not in allowed_kinds:
                raise HTTPException(400, f"unsupported kind: {f.kind}")
            if f.kind in seen:
                raise HTTPException(400, f"duplicated kind: {f.kind}")
            seen.add(f.kind)

        uploads: Dict[Kind, UploadItem] = {}

        for f in request.files:
            key = account_asset_key(str(user.id), f.kind, f.ext)

            response = presign_put_public("public", key, f.content_type)
            
            uploads[f.kind] = PresignResponseItem(
                key=response["key"],
                upload_url=response["upload_url"],
                expires_in=response["expires_in"],
                required_headers=response["required_headers"]
            )

        return AccountPresignResponse(uploads=uploads)
    except Exception as e:
        logger.error("アップロードURL生成エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/posts")
def get_post_status(
    user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    投稿ステータスを取得
    """
    try:
        posts_data = get_post_status_by_user_id(db, user.id)
        
        return AccountPostStatusResponse(
            pending_posts=_convert_posts(posts_data["pending_posts"]),
            rejected_posts=_convert_posts(posts_data["rejected_posts"]),
            unpublished_posts=_convert_posts(posts_data["unpublished_posts"]),
            deleted_posts=_convert_posts(posts_data["deleted_posts"]),
            approved_posts=_convert_posts(posts_data["approved_posts"]),
            reserved_posts=_convert_posts(posts_data["reserved_posts"])
        )
    except Exception as e:
        logger.error("投稿ステータス取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/post/{post_id}", response_model=AccountPostDetailResponse)
def get_account_post_detail(
    post_id: str,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    クリエイター自身の投稿詳細を取得（編集・管理用）
    """
    try:
        #投稿基本情報取得
        post_base_info = get_post_detail_for_creator(db, UUID(post_id), current_user.id)


        if not post_base_info:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        # カテゴリー情報取得
        category_records = get_post_categories(db, post_id)
        category_ids = [str(rec.category_id) for rec in category_records]

        # プラン情報を取得
        post_plans = get_post_plans(db, post_id)
        # plan_list = [{'id': str(rec.plan_id), 'name': rec.plan.name} for rec in post_plans]

        # メディア情報を取得
        post_data = get_post_by_id(db, post_id)
        if not post_data:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        media_assets = post_data.get('media_assets', {})
        processed_media_assets = {
            media_asset_id: {
                **media_asset_data,
                "storage_key": resolve_media_asset_storage_key(media_asset_data),
            }
            for media_asset_id, media_asset_data in media_assets.items()
        }

        plan_list_response = []
        for plan in post_plans:
            plan_list_response.append(
                {
                    "id": str(plan.plan_id),
                    "name": getattr(plan.plan, "name", None),
                }
            )

        return AccountPostDetailResponse(
            id=str(post_base_info["post"].id),
            description=post_base_info["post"].description,
            reject_comments=post_base_info["post"].reject_comments if post_base_info["post"].reject_comments else None,
            likes_count=post_base_info["likes_count"],
            comments_count=post_base_info["comments_count"],
            purchase_count=post_base_info["purchase_count"],
            creator_name=post_base_info["creator_name"],
            username=post_base_info["username"],
            creator_avatar_url=f"{BASE_URL}/{post_base_info['creator_avatar_url']}" if post_base_info.get('creator_avatar_url') else None,
            price=int(post_base_info["price"]) if post_base_info["price"] is not None else 0,
            currency=post_base_info["currency"] or "JPY",
            scheduled_at=post_base_info["post"].scheduled_at.isoformat() if post_base_info["post"].scheduled_at else None,
            expiration_at=post_base_info["post"].expiration_at.isoformat() if post_base_info["post"].expiration_at else None,
            duration=post_base_info.get("duration"),
            is_video=post_base_info["is_video"],
            post_type=post_base_info["post"].post_type,
            status=post_base_info["post"].status,
            visibility=post_base_info["post"].visibility,
            category_ids=category_ids,
            tags=post_base_info.get("tags"),
            plan_list=plan_list_response,
            media_assets=processed_media_assets,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="無効な投稿IDです")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("投稿詳細取得エラーが発生しました", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/plans")
def get_plans(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    プラン一覧を取得
    """
    try:
        plan_data = get_plan_by_user_id(db, current_user.id)

        # subscribed_plan_detailsのURLを構築
        subscribed_plan_details = []
        for plan in plan_data.get("subscribed_plan_details", []):
            subscribed_plan_details.append({
                **plan,
                "creator_avatar_url": f"{BASE_URL}/{plan['creator_avatar_url']}" if plan.get('creator_avatar_url') else None,
                "thumbnail_keys": [f"{BASE_URL}/{key}" for key in plan.get('thumbnail_keys', [])]
            })

        return PlansSubscribedInfo(
            plan_count=plan_data["plan_count"] if plan_data else 0,
            total_price=plan_data["total_price"] if plan_data else 0,
            subscribed_plan_count=plan_data["subscribed_plan_count"] if plan_data else 0,
            subscribed_total_price=plan_data["subscribed_total_price"] if plan_data else 0,
            subscribed_plan_names=plan_data["subscribed_plan_names"] if plan_data else [],
            subscribed_plan_details=subscribed_plan_details,
        )
    except Exception as e:
        logger.error("プラン一覧取得エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/bookmarks", response_model=BookmarkedPostsResponse)
def get_bookmarks(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    ブックマークした投稿一覧を取得
    """
    try:
        bookmarks_data = get_bookmarked_posts_by_user_id(db, current_user.id)

        bookmarks = []
        for post, profile_name, username, avatar_url, thumbnail_key, duration_sec, likes_count, comments_count, post_price, post_currency, bookmarked_at in bookmarks_data:
            # 動画時間をフォーマット
            duration = None
            if duration_sec:
                minutes = int(duration_sec // 60)
                seconds = int(duration_sec % 60)
                duration = f"{minutes}:{seconds:02d}"

            bookmark = PostCardResponse(
                id=post.id,
                thumbnail_url=f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None,
                title=post.description or "",
                creator_avatar=f"{BASE_URL}/{avatar_url}" if avatar_url else None,
                creator_name=profile_name,
                creator_username=username,
                likes_count=likes_count or 0,
                comments_count=comments_count or 0,
                duration=duration,
                is_video=(post.post_type == PostType.VIDEO),  # 2が動画
                created_at=bookmarked_at,
                price=int(post_price) if post_price else None,
                currency=post_currency or "JPY"
            )
            bookmarks.append(bookmark)

        return BookmarkedPostsResponse(bookmarks=bookmarks)
    except Exception as e:
        logger.error("ブックマーク一覧取得エラー:", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/likes", response_model=LikedPostsListResponse)
def get_likes(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    いいねした投稿一覧を取得
    """
    try:
        liked_posts_data = get_liked_posts_list_by_user_id(db, current_user.id)

        liked_posts = []
        for post, profile_name, username, avatar_url, thumbnail_key, duration_sec, likes_count, comments_count, post_price, post_currency, liked_at in liked_posts_data:
            # 動画時間をフォーマット
            duration = None
            if duration_sec:
                minutes = int(duration_sec // 60)
                seconds = int(duration_sec % 60)
                duration = f"{minutes}:{seconds:02d}"

            liked_post = PostCardResponse(
                id=post.id,
                thumbnail_url=f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None,
                title=post.description or "",
                creator_avatar=f"{BASE_URL}/{avatar_url}" if avatar_url else None,
                creator_name=profile_name,
                creator_username=username,
                likes_count=likes_count or 0,
                comments_count=comments_count or 0,
                duration=duration,
                is_video=(post.post_type == PostType.VIDEO),  # 1が動画
                created_at=liked_at,
                price=int(post_price) if post_price else None,
                currency=post_currency or "JPY"
            )
            liked_posts.append(liked_post)

        return LikedPostsListResponse(liked_posts=liked_posts)
    except Exception as e:
        logger.error("いいね一覧取得エラー:", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/bought", response_model=BoughtPostsResponse)
def get_bought(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    購入済み投稿一覧を取得
    """
    try:
        bought_posts_data = get_bought_posts_by_user_id(db, current_user.id)

        bought_posts = []
        for post, profile_name, username, avatar_url, thumbnail_key, duration_sec, likes_count, comments_count, purchased_at in bought_posts_data:
            # 動画時間をフォーマット
            duration = None
            if duration_sec:
                minutes = int(duration_sec // 60)
                seconds = int(duration_sec % 60)
                duration = f"{minutes}:{seconds:02d}"

            bought_post = PostCardResponse(
                id=post.id,
                thumbnail_url=f"{BASE_URL}/{thumbnail_key}" if thumbnail_key else None,
                title=post.description or "",
                creator_avatar=f"{BASE_URL}/{avatar_url}" if avatar_url else None,
                creator_name=profile_name,
                creator_username=username,
                likes_count=likes_count or 0,
                comments_count=comments_count or 0,
                duration=duration,
                is_video=(post.post_type == 2),  # 2が動画
                created_at=purchased_at
            )
            bought_posts.append(bought_post)

        return BoughtPostsResponse(bought_posts=bought_posts)
    except Exception as e:
        logger.error("購入済み一覧取得エラー:", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/profile-image/submit", response_model=ProfileImageSubmissionResponse)
def submit_profile_image(
    submission: ProfileImageSubmissionCreate,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    プロフィール画像を申請

    アップロード完了後に申請を作成します。
    管理者による承認後、プロフィールに反映されます。

    - **image_type**: 1=avatar, 2=cover
    - **storage_key**: S3にアップロードした画像のキー
    """
    try:
        # 同じタイプで申請中のものがあるかチェック
        existing_submission = profile_image_crud.get_pending_submission_by_user_and_type(
            db, current_user.id, submission.image_type
        )

        if existing_submission:
            raise HTTPException(
                status_code=400,
                detail="既に申請中の画像があります。承認または却下後に再申請してください。"
            )

        # 新規申請作成
        new_submission = profile_image_crud.create_submission(
            db=db,
            user_id=current_user.id,
            image_type=submission.image_type,
            storage_key=submission.storage_key
        )

        db.commit()
        db.refresh(new_submission)

        return ProfileImageSubmissionResponse.from_orm(new_submission)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("プロフィール画像申請エラー:", e)
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/profile-image/status", response_model=ProfileImageStatusResponse)
def get_profile_image_status(
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    プロフィール画像の申請状況を取得

    アバターとカバー画像それぞれの最新申請状況を返します。
    """
    try:
        submissions = profile_image_crud.get_user_submissions(db, current_user.id)

        return ProfileImageStatusResponse(
            avatar_submission=submissions["avatar_submission"],
            cover_submission=submissions["cover_submission"]
        )
    except Exception as e:
        logger.error("申請状況取得エラー:", e)
        raise HTTPException(status_code=500, detail=str(e))

# データ変換用のヘルパー関数
def _convert_posts(posts_list):
    result = []
    for row in posts_list:
        # タプルの最初の要素がPostsオブジェクト
        post_obj = row[0]
        
        # 動画時間をフォーマット
        duration = None
        if row.duration_sec:
            minutes = int(row.duration_sec // 60)
            seconds = int(row.duration_sec % 60)
            duration = f"{minutes:02d}:{seconds:02d}"

        # 投稿タイプを判定
        is_video = post_obj.post_type == 1 if post_obj.post_type else False  # PostType.VIDEO = 1

        result.append(AccountPostResponse(
            id=str(post_obj.id),
            description=post_obj.description,
            thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}" if row.thumbnail_key else None,
            likes_count=row.likes_count or 0,
            comments_count=row.comments_count or 0,
            purchase_count=row.purchase_count or 0,
            creator_name=row.profile_name,
            username=row.username,
            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}" if row.avatar_url else None,
            price=row.post_price or 0,
            currency=row.post_currency or "JPY",
            created_at=post_obj.created_at.isoformat() if post_obj.created_at else None,
            duration=duration,
            is_video=is_video
        ))
    return result


@router.put("/post/{post_id}")
def update_account_post(
    post_id: str,
    request: AccountPostUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
) -> AccountPostUpdateResponse:
    """
    クリエイターが自分の投稿を更新

    Args:
        post_id: 投稿ID
        request: 更新リクエスト（status, visibility, scheduled_at）
        db: データベースセッション
        current_user: 現在のユーザー

    Returns:
        AccountPostUpdateResponse: 更新結果
    """

    try:
        # リクエストデータを辞書に変換（Noneでない値のみ）
        update_data = {}
        if request.status is not None:
            update_data['status'] = request.status
        if request.visibility is not None:
            update_data['visibility'] = request.visibility
        if request.scheduled_at is not None:
            update_data['scheduled_at'] = request.scheduled_at
        if request.description is not None:
            update_data['description'] = request.description

        # 投稿を更新
        updated_post = update_post_by_creator(
            db=db,
            post_id=UUID(post_id),
            creator_user_id=current_user.id,
            update_data=update_data
        )

        if not updated_post:
            raise HTTPException(
                status_code=404,
                detail="投稿が見つからないか、更新する権限がありません"
            )

        db.commit()

        return AccountPostUpdateResponse(
            message="投稿を更新しました",
            success=True
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"無効な投稿ID: {str(e)}")
    except Exception as e:
        db.rollback()
        logger.error(f"投稿更新エラー: {e}")
        raise HTTPException(status_code=500, detail="投稿の更新に失敗しました")

@router.post("/setting-email")
async def setting_email(
    email_setting: AccountEmailSettingRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    メールアドレスを設定
    """
    try:
        if email_setting.type == 1:
            logger.info(f"メールアドレス設定: {email_setting.email}")
            email_existing = db.query(Users).filter(Users.email == email_setting.email).first()
            if email_existing or (current_user.email == email_setting.email):
                return Response(content="既に使用されているメールアドレスです。", status_code=400)
            token = __generate_email_verification_token(db, email_setting.email, current_user.id)
            if not token:
                raise HTTPException(status_code=500, detail="メールアドレスの認証トークンの生成に失敗しました")
            verify_url = f"{os.environ.get('FRONTEND_URL')}/setting/verify-email?token={token}"
            send_email_verification(to=email_setting.email, verify_url=verify_url, display_name=current_user.profile_name)
        elif email_setting.type == 2:
            logger.info(f"メールアドレス認証: {email_setting.token}")
            payload = __verify_email_verification_token(db, email_setting.token)
            exp_dt = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            if exp_dt < datetime.now(timezone.utc):
                return Response(content="リンクが無効か、期限切れです。", status_code=400)
            current_user.email = payload["email"]
            current_user.email_verified_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(current_user)
            return {"message": "メールアドレスを認証しました", "success": True}
    except Exception as e:
        db.rollback()
        logger.error(f"メールアドレス設定エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def __generate_email_verification_token(db: Session, email: str, user_id: UUID) -> str:
    """
    メールアドレスの認証トークンを生成
    """
    exp_time = datetime.now(timezone.utc) + timedelta(hours=48)
    payload = {
        "user_id": str(user_id),
        "email": email,
        "exp": exp_time
    }
    secret_key = os.environ.get("SECRET_KEY", "SECRET_KEY")
    token = jwt.encode(payload, secret_key, algorithm="HS256")
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token

def __verify_email_verification_token(db: Session, token: str) -> dict:
    """
    メールアドレスの認証トークンを検証
    """
    secret_key = os.environ.get("SECRET_KEY", "SECRET_KEY")
    try:
        payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="リンクが無効か、期限切れです。")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="不正なトークンです。")
    return payload