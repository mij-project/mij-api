from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from app.api.commons.utils import get_video_duration
from app.constants.enums import PostType
from app.db.base import get_db
from app.crud.post_crud import get_posts_by_category_slug
from app.schemas.post import PaginatedPostCategoryResponse, PostCategoryResponse
from app.models.categories import Categories
from os import getenv
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()

BASE_URL = getenv("CDN_BASE_URL")


@router.get("/", response_model=PaginatedPostCategoryResponse)
async def get_category_by_slug(
    slug: str = Query(..., description="Category Slug"),
    page: int = 1,
    per_page: int = 100,
    db: Session = Depends(get_db),
):
    try:
        # カテゴリ情報を取得（投稿がない場合でもカテゴリ名を返すため）
        category = db.query(Categories).filter(Categories.slug == slug).first()
        if not category:
            raise HTTPException(status_code=404, detail="Category not found")

        posts, total = get_posts_by_category_slug(db, slug, page, per_page)
        next_page, previous_page, has_next, has_previous = __process_pagination(
            posts, page, per_page
        )
        response_posts = []
        for post in posts:
            if not post.post_id:
                continue
            response_posts.append(
                PostCategoryResponse(
                    id=post.post_id,
                    description=post.description,
                    thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}"
                    if post.thumbnail_key
                    else None,
                    likes_count=post.likes_count,
                    official=post.offical_flg if hasattr(post, 'offical_flg') else False,
                    creator_name=post.profile_name,
                    username=post.username,
                    creator_avatar_url=f"{BASE_URL}/{post.avatar_url}"
                    if post.avatar_url
                    else None,
                    duration=get_video_duration(post.duration_sec)
                    if post.post_type == PostType.VIDEO and post.duration_sec
                    else ("画像" if post.post_type == PostType.IMAGE else ""),
                    category_name=category.name,
                )
            )
        return PaginatedPostCategoryResponse(
            posts=response_posts,
            total=total,
            page=page,
            per_page=per_page,
            has_next=has_next,
            has_previous=has_previous,
            category_name=category.name,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("カテゴリー取得に失敗しました", e)
        raise HTTPException(status_code=500, detail=str(e))


def __process_pagination(result: list, page: int, per_page: int) -> dict:
    """
    Process pagination

    Args:
        result: Result is result
        page: Page number
        per_page: Number of items per page
    Returns:
        next_page: int | None, previous_page: int | None, has_next: bool, has_previous: bool
    """

    if len(result) == per_page:
        next_page = page + 1
        has_next = True
    else:
        next_page = None
        has_next = False
    if page > 1:
        previous_page = page - 1
        has_previous = True
    else:
        previous_page = None
        has_previous = False

    return next_page, previous_page, has_next, has_previous
