from os import getenv
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List
from uuid import UUID

from app.db.base import get_db
from app.deps.auth import get_current_user
from app.models.user import Users
from app.crud import search_crud, search_history_crud
from app.schemas.search import (
    CreatorSearchResult,
    PostCreatorInfo,
    PostSearchResult,
    HashtagSearchResult,
    SearchSectionResponse,
    SearchResponse,
    SearchHistoryItem,
    SearchHistoryResponse,
)

BASE_URL = getenv("CDN_BASE_URL")
router = APIRouter()


# --- Endpoints ---

@router.get("/search", response_model=SearchResponse)
def search(
    query: str = Query(..., min_length=1, description="検索クエリ"),
    type: str = Query("all", regex="^(all|users|posts|hashtags|creators|paid_posts)$", description="検索タイプ"),
    sort: str = Query("relevance", regex="^(relevance|popularity)$", description="ソート基準"),
    category_ids: Optional[List[UUID]] = Query(None, description="カテゴリフィルター"),
    post_type: Optional[int] = Query(None, ge=1, le=2, description="投稿タイプ (1=VIDEO, 2=IMAGE)"),
    page: int = Query(1, ge=1, description="ページ番号"),
    per_page: int = Query(20, ge=1, le=100, description="1ページあたりの件数"),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    統合検索API
    """
    try:
        offset = (page - 1) * per_page
        total_results = 0
        search_history_saved = False

        response_data = {
            "query": query,
            "total_results": 0,
            "search_history_saved": False
        }

        # クリエイター検索
        if type in ["all", "users", "creators"]:
            # creators タブの場合は最新投稿も取得
            include_recent_posts = (type == "creators")

            creators_results, creators_total = search_crud.search_creators(
                db,
                query=query,
                sort=sort,
                limit=5 if type == "all" else per_page,
                offset=0 if type == "all" else offset,
                include_recent_posts=include_recent_posts
            )

            creators_items = []
            for r in creators_results:
                recent_posts = []
                if hasattr(r, 'recent_posts'):
                    recent_posts = [
                        {"id": p["id"], "thumbnail_url": f"{BASE_URL}/{p['thumbnail_url']}" if p.get('thumbnail_url') else None}
                        for p in r.recent_posts
                    ]

                creators_items.append(
                    CreatorSearchResult(
                        id=r.id,
                        profile_name=r.profile_name,
                        username=r.username,
                        avatar_url=f"{BASE_URL}/{r.avatar_url}" if r.avatar_url else None,
                        bio=r.bio,
                        followers_count=r.followers_count,
                        is_verified=r.is_verified,
                        posts_count=r.posts_count,
                        recent_posts=recent_posts
                    )
                )

            response_data["creators"] = SearchSectionResponse(
                total=creators_total,
                items=creators_items,
                has_more=creators_total > len(creators_items)
            )
            total_results += creators_total

        # 投稿検索
        if type in ["all", "posts", "paid_posts"]:
            paid_only = (type == "paid_posts")

            posts_results, posts_total = search_crud.search_posts(
                db,
                query=query,
                sort=sort,
                category_ids=[str(cid) for cid in category_ids] if category_ids else None,
                post_type=post_type,
                paid_only=paid_only,
                limit=10 if type == "all" else per_page,
                offset=0 if type == "all" else offset
            )

            posts_items = [
                PostSearchResult(
                    id=r.id,
                    description=r.description,
                    post_type=r.post_type,
                    visibility=r.visibility,
                    likes_count=r.likes_count,
                    thumbnail_key=f"{BASE_URL}/{r.thumbnail_key}" if r.thumbnail_key else None,
                    video_duration=int(r.video_duration) if r.video_duration else None,
                    creator=PostCreatorInfo(
                        id=r.creator_id,
                        profile_name=r.profile_name,
                        username=r.username,
                        avatar_url=r.avatar_url
                    ),
                    created_at=r.created_at.isoformat()
                ) for r in posts_results
            ]

            response_data["posts"] = SearchSectionResponse(
                total=posts_total,
                items=posts_items,
                has_more=posts_total > len(posts_items)
            )
            total_results += posts_total

        # ハッシュタグ検索
        if type in ["all", "hashtags"]:
            hashtags_results, hashtags_total = search_crud.search_hashtags(
                db,
                query=query,
                limit=5 if type == "all" else per_page,
                offset=0 if type == "all" else offset
            )

            hashtags_items = [
                HashtagSearchResult(
                    id=r.id,
                    name=r.name,
                    slug=r.slug,
                    posts_count=r.posts_count
                ) for r in hashtags_results
            ]

            response_data["hashtags"] = SearchSectionResponse(
                total=hashtags_total,
                items=hashtags_items,
                has_more=hashtags_total > len(hashtags_items)
            )
            total_results += hashtags_total

        response_data["total_results"] = total_results

        # 検索履歴保存 (結果が1件以上ある場合のみ)
        # if total_results > 0:
        try:
            search_history_crud.create_or_update_search_history(
                db,
                user_id=current_user.id,
                query=query,
                search_type=type,
                filters={
                    "category_ids": [str(cid) for cid in category_ids] if category_ids else None,
                    "post_type": post_type
                }
            )
            response_data["search_history_saved"] = True
        except Exception as e:
            # 検索履歴保存エラーは無視
            pass

        return SearchResponse(**response_data)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.get("/search/history", response_model=SearchHistoryResponse)
def get_search_history(
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    検索履歴取得
    """
    histories = search_history_crud.get_search_histories(
        db,
        user_id=current_user.id,
        limit=limit
    )

    items = [
        SearchHistoryItem(
            id=h.id,
            query=h.query,
            search_type=h.search_type,
            filters=h.filters,
            created_at=h.created_at.isoformat()
        ) for h in histories
    ]

    return SearchHistoryResponse(items=items)


@router.delete("/search/history/{history_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_search_history_item(
    history_id: UUID,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    検索履歴削除 (個別)
    """
    deleted = search_history_crud.delete_search_history(
        db,
        history_id=history_id,
        user_id=current_user.id
    )

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search history not found"
        )

    return None


@router.delete("/search/history", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_search_history(
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user)
):
    """
    検索履歴全削除
    """
    search_history_crud.delete_all_search_histories(
        db,
        user_id=current_user.id
    )

    return None
