from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Dict
from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.schemas.account import (
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
from app.crud.sales_crud import get_total_sales
from app.crud.plan_crud import get_plan_by_user_id
from app.crud.purchases_crud import get_single_purchases_count_by_user_id, get_single_purchases_by_user_id
from app.crud.user_crud import check_profile_name_exists, update_user
from app.crud.profile_crud import get_profile_by_user_id, get_profile_info_by_user_id, get_profile_edit_info_by_user_id, update_profile
from app.crud import profile_image_crud
from app.services.s3.keygen import account_asset_key
from app.services.s3.presign import presign_put_public
import os

router = APIRouter()
BASE_URL = os.getenv("CDN_BASE_URL")

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
        )
        
        # 売上
        total_sales = get_total_sales(db, current_user.id)
        sales_info = SalesInfo(
            total_sales=total_sales or 0,
        )

        # プラン情報
        plan_data = get_plan_by_user_id(db, current_user.id)
        # 単品購入データ
        single_purchases_count = get_single_purchases_count_by_user_id(db, current_user.id)
        single_purchases_data = get_single_purchases_by_user_id(db, current_user.id)

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
        print("アカウント情報取得エラーが発生しました", e)
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
        print("プロフィール編集情報取得エラー:", e)
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
        if update_data.name:
            if check_profile_name_exists(db, update_data.name) and update_data.name != current_user.profile_name:
                raise HTTPException(status_code=400, detail="このユーザー名は既に使用されています")

            user = update_user(db, current_user.id, update_data.name)

        if update_data.username:
            profile = update_profile(db, current_user.id, update_data)

        db.commit()
        db.refresh(user)
        db.refresh(profile)

        return AccountUpdateResponse(
            message="アカウント情報が正常に更新されました",
            success=True
        )
    except Exception as e:
        print("アカウント情報更新エラーが発生しました", e)
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
        print("アップロードURL生成エラーが発生しました", e)
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
        
        # データ変換用のヘルパー関数
        def convert_posts(posts_list):
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
        
        return AccountPostStatusResponse(
            pending_posts=convert_posts(posts_data["pending_posts"]),
            rejected_posts=convert_posts(posts_data["rejected_posts"]),
            unpublished_posts=convert_posts(posts_data["unpublished_posts"]),
            deleted_posts=convert_posts(posts_data["deleted_posts"]),
            approved_posts=convert_posts(posts_data["approved_posts"])
        )
    except Exception as e:
        print("投稿ステータス取得エラーが発生しました", e)
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
        from uuid import UUID

        post_data = get_post_detail_for_creator(db, UUID(post_id), current_user.id)

        if not post_data:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        # メディア情報を取得
        media_info = post_data.get("media_info", {})
        sample_video_url = media_info.get("sample_video", {}).get("url") if media_info.get("sample_video") else None
        main_video_url = media_info.get("main_video", {}).get("url") if media_info.get("main_video") else None
        ogp_image_url = media_info.get("ogp_image", {}).get("url") if media_info.get("ogp_image") else None
        image_urls = [img.get("url") for img in media_info.get("images", []) if img.get("url")]

        return AccountPostDetailResponse(
            id=str(post_data["post"].id),
            description=post_data["post"].description,
            thumbnail_url=f"{BASE_URL}/{post_data['thumbnail_key']}" if post_data.get('thumbnail_key') else None,
            ogp_image_url=ogp_image_url if ogp_image_url else None,
            likes_count=post_data["likes_count"],
            comments_count=post_data["comments_count"],
            purchase_count=post_data["purchase_count"],
            creator_name=post_data["creator_name"],
            username=post_data["username"],
            creator_avatar_url=f"{BASE_URL}/{post_data['creator_avatar_url']}" if post_data.get('creator_avatar_url') else None,
            price=post_data["price"],
            currency=post_data["currency"],
            created_at=post_data["post"].created_at.isoformat(),
            updated_at=post_data["post"].updated_at.isoformat(),
            duration=post_data.get("duration"),
            is_video=post_data["is_video"],
            post_type=post_data["post"].post_type,
            status=post_data["post"].status,
            visibility=post_data["post"].visibility,
            sample_video_url=sample_video_url,
            main_video_url=main_video_url,
            image_urls=image_urls,
            category_ids=post_data.get("category_ids", []),
            tags=post_data.get("tags"),
            plan_ids=post_data.get("plan_ids", [])
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="無効な投稿IDです")
    except HTTPException:
        raise
    except Exception as e:
        print("投稿詳細取得エラーが発生しました", e)
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/post/{post_id}", response_model=AccountPostUpdateResponse)
def update_account_post(
    post_id: str,
    request_data: AccountPostUpdateRequest,
    current_user: Users = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    クリエイター自身の投稿を更新（非公開化、削除、編集など）
    """
    try:
        from uuid import UUID

        # 更新データを準備
        update_data = request_data.dict(exclude_unset=True)

        if not update_data:
            raise HTTPException(status_code=400, detail="更新するデータがありません")

        # 投稿を更新
        updated_post = update_post_by_creator(db, UUID(post_id), current_user.id, update_data)

        if not updated_post:
            raise HTTPException(status_code=404, detail="投稿が見つかりません")

        db.commit()

        return AccountPostUpdateResponse(
            message="投稿を更新しました",
            success=True
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="無効な投稿IDです")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print("投稿更新エラーが発生しました", e)
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
        print("プラン一覧取得エラーが発生しました", e)
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
        for post, profile_name, username, avatar_url, thumbnail_key, duration_sec, likes_count, comments_count, bookmarked_at in bookmarks_data:
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
                is_video=(post.post_type == 2),  # 2が動画
                created_at=bookmarked_at
            )
            bookmarks.append(bookmark)

        return BookmarkedPostsResponse(bookmarks=bookmarks)
    except Exception as e:
        print("ブックマーク一覧取得エラー:", e)
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
        for post, profile_name, username, avatar_url, thumbnail_key, duration_sec, likes_count, comments_count, liked_at in liked_posts_data:
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
                is_video=(post.post_type == 2),  # 2が動画
                created_at=liked_at
            )
            liked_posts.append(liked_post)

        return LikedPostsListResponse(liked_posts=liked_posts)
    except Exception as e:
        print("いいね一覧取得エラー:", e)
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
        print("購入済み一覧取得エラー:", e)
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
        print("プロフィール画像申請エラー:", e)
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
        print("申請状況取得エラー:", e)
        raise HTTPException(status_code=500, detail=str(e))

