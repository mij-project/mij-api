from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.commons.utils import get_video_duration
from app.constants.enums import PostType
from app.crud.time_sale_crud import get_post_sale_flag_map
from app.db.base import get_db
from app.crud.creator_crud import (
    get_ranking_creators_overall,
    get_ranking_creators_categories_overall,
    get_ranking_creators_categories_detail,
)
from app.crud.post_crud import (
    get_post_ranking_overall,
    get_ranking_posts_categories_overall,
    get_ranking_posts_detail_overall,
    get_ranking_posts_detail_categories,
)
from app.deps.auth import get_current_user_optional
from app.models import Users
from app.schemas.ranking import (
    RankingCategoriesResponse,
    RankingCreatorsCategories,
    RankingCreatorsCategoriesResponse,
    RankingPostsCategoriesDetailResponse,
    RankingPostsCategoriesResponse,
    RankingCreators,
    RankingCreatorsDetailResponse,
    RankingCreatorsResponse,
    RankingOverallResponse,
    RankingPostsAllTimeResponse,
    RankingPostsDetailDailyResponse,
    RankingPostsDetailResponse,
    RankingPostsMonthlyResponse,
    RankingPostsWeeklyResponse,
    RankingPostsDailyResponse,
)
from os import getenv
from app.core.logger import Logger

logger = Logger.get_logger()
BASE_URL = getenv("CDN_BASE_URL")

router = APIRouter()


@router.get("/posts")
async def get_ranking_posts(
    type: str = Query(..., description="Type, allowed values: overall, categories"),
    db: Session = Depends(get_db),
):
    try:
        if type == "overall":
            return _get_ranking_posts_overall(db)
        if type == "categories":
            return _get_ranking_posts_categories(db)

    except Exception as e:
        logger.error("エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


def _get_ranking_posts_overall(db: Session) -> RankingOverallResponse:
    """
    Get overall ranking posts

    Args:
        db: Database session
    Returns:
        RankingResponse: Ranking posts
    """
    ranking_posts_all_time = get_post_ranking_overall(db, limit=6, period="all_time")
    # ranking_posts_monthly = get_ranking_posts_overall_monthly(db, limit=6)
    ranking_posts_monthly = get_post_ranking_overall(db, limit=6, period="monthly")
    # ranking_posts_weekly = get_ranking_posts_overall_weekly(db, limit=6)
    ranking_posts_weekly = get_post_ranking_overall(db, limit=6, period="weekly")
    # ranking_posts_daily = get_ranking_posts_overall_daily(db, limit=6)
    ranking_posts_daily = get_post_ranking_overall(db, limit=6, period="daily")

    tracking_daily = [str(post.Posts.id) for post in ranking_posts_daily]
    if len(ranking_posts_daily) < 6:
        for post in ranking_posts_weekly:
            if str(post.Posts.id) in tracking_daily:
                continue
            if len(ranking_posts_daily) < 6:
                ranking_posts_daily.append(post)
                tracking_daily.append(str(post.Posts.id))
            else:
                break
        for post in ranking_posts_monthly:
            if str(post.Posts.id) in tracking_daily:
                continue
            if len(ranking_posts_daily) < 6:
                ranking_posts_daily.append(post)
                tracking_daily.append(str(post.Posts.id))
            else:
                break
        for post in ranking_posts_all_time:
            if str(post.Posts.id) in tracking_daily:
                continue
            if len(ranking_posts_daily) < 6:
                ranking_posts_daily.append(post)
                tracking_daily.append(str(post.Posts.id))
            else:
                break
    tracking_weekly = [str(post.Posts.id) for post in ranking_posts_weekly]
    if len(ranking_posts_weekly) < 6:
        for post in ranking_posts_monthly:
            if str(post.Posts.id) in tracking_weekly:
                continue
            if len(ranking_posts_weekly) < 6:
                ranking_posts_weekly.append(post)
                tracking_weekly.append(str(post.Posts.id))
            else:
                break
        for post in ranking_posts_all_time:
            if str(post.Posts.id) in tracking_weekly:
                continue
            if len(ranking_posts_weekly) < 6:
                ranking_posts_weekly.append(post)
                tracking_weekly.append(str(post.Posts.id))
            else:
                break
    tracking_monthly = [str(post.Posts.id) for post in ranking_posts_monthly]
    if len(ranking_posts_monthly) < 6:
        for post in ranking_posts_all_time:
            if str(post.Posts.id) in tracking_monthly:
                continue
            if len(ranking_posts_monthly) < 6:
                ranking_posts_monthly.append(post)
                tracking_monthly.append(str(post.Posts.id))
            else:
                break

    return RankingOverallResponse(
        all_time=[
            RankingPostsAllTimeResponse(
                id=str(post.Posts.id),  # UUIDを文字列に変換
                description=post.Posts.description,
                thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}"
                if post.thumbnail_key
                else None,
                # likes_count=post.likes_count,
                likes_count=0,
                creator_name=post.profile_name,
                official=post.offical_flg if hasattr(post, "offical_flg") else False,
                username=post.username,
                creator_avatar_url=f"{BASE_URL}/{post.avatar_url}"
                if post.avatar_url
                else None,
                rank=idx + 1,
                duration=get_video_duration(post.duration_sec)
                if post.Posts.post_type == PostType.VIDEO and post.duration_sec
                else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
                is_time_sale=post.Posts.is_time_sale,
            )
            for idx, post in enumerate(ranking_posts_all_time)
        ],
        monthly=[
            RankingPostsMonthlyResponse(
                id=str(post.Posts.id),  # UUIDを文字列に変換
                description=post.Posts.description,
                thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}"
                if post.thumbnail_key
                else None,
                # likes_count=post.likes_count,
                likes_count=0,
                creator_name=post.profile_name,
                official=post.offical_flg if hasattr(post, "offical_flg") else False,
                username=post.username,
                creator_avatar_url=f"{BASE_URL}/{post.avatar_url}"
                if post.avatar_url
                else None,
                rank=idx + 1,
                duration=get_video_duration(post.duration_sec)
                if post.Posts.post_type == PostType.VIDEO and post.duration_sec
                else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
                is_time_sale=post.Posts.is_time_sale,
            )
            for idx, post in enumerate(ranking_posts_monthly)
        ],
        weekly=[
            RankingPostsWeeklyResponse(
                id=str(post.Posts.id),  # UUIDを文字列に変換
                description=post.Posts.description,
                thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}"
                if post.thumbnail_key
                else None,
                # likes_count=post.likes_count,
                likes_count=0,
                creator_name=post.profile_name,
                official=post.offical_flg if hasattr(post, "offical_flg") else False,
                username=post.username,
                creator_avatar_url=f"{BASE_URL}/{post.avatar_url}"
                if post.avatar_url
                else None,
                rank=idx + 1,
                duration=get_video_duration(post.duration_sec)
                if post.Posts.post_type == PostType.VIDEO and post.duration_sec
                else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
                is_time_sale=post.Posts.is_time_sale,
            )
            for idx, post in enumerate(ranking_posts_weekly)
        ],
        daily=[
            RankingPostsDailyResponse(
                id=str(post.Posts.id),  # UUIDを文字列に変換
                description=post.Posts.description,
                thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}"
                if post.thumbnail_key
                else None,
                # likes_count=post.likes_count,
                likes_count=0,
                creator_name=post.profile_name,
                official=post.offical_flg if hasattr(post, "offical_flg") else False,
                username=post.username,
                creator_avatar_url=f"{BASE_URL}/{post.avatar_url}"
                if post.avatar_url
                else None,
                rank=idx + 1,
                duration=get_video_duration(post.duration_sec)
                if post.Posts.post_type == PostType.VIDEO and post.duration_sec
                else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
                is_time_sale=post.Posts.is_time_sale,
            )
            for idx, post in enumerate(ranking_posts_daily)
        ],
    )


def _get_ranking_posts_categories(db: Session) -> RankingCategoriesResponse:
    """
    Get categories ranking posts

    Args:
        db: Database session
    Returns:
        RankingCategoriesResponse: Ranking posts
    """
    # ranking_posts_categories_all_time = get_ranking_posts_categories_all_time(
    #     db, limit=6
    # )
    ranking_posts_categories_all_time = get_ranking_posts_categories_overall(
        db, limit_per_category=6, period="all_time"
    )
    ranking_posts_categories_daily = get_ranking_posts_categories_overall(
        db, limit_per_category=6, period="daily"
    )
    ranking_posts_categories_weekly = get_ranking_posts_categories_overall(
        db, limit_per_category=6, period="weekly"
    )
    ranking_posts_categories_monthly = get_ranking_posts_categories_overall(
        db, limit_per_category=6, period="monthly"
    )

    response = {
        "daily": __arrange_ranking_posts_categories(
            db, ranking_posts_categories_daily, "daily"
        ),
        "weekly": __arrange_ranking_posts_categories(
            db, ranking_posts_categories_weekly, "weekly"
        ),
        "monthly": __arrange_ranking_posts_categories(
            db, ranking_posts_categories_monthly, "monthly"
        ),
        "all_time": __arrange_ranking_posts_categories(
            db, ranking_posts_categories_all_time, "all_time"
        ),
    }
    return RankingCategoriesResponse(
        all_time=response["all_time"],
        daily=response["daily"],
        weekly=response["weekly"],
        monthly=response["monthly"],
    )


def __arrange_ranking_posts_categories(
    db: Session, ranking_posts_categories: list, period: str
) -> dict:
    grouped: dict[str, RankingPostsCategoriesResponse] = {}
    post_ids = [
        row.post_id for row in ranking_posts_categories if getattr(row, "post_id", None)
    ]
    sale_map = get_post_sale_flag_map(db, post_ids)
    for row in ranking_posts_categories:
        if not row.profile_name:
            continue

        category_id = str(row.category_id)
        category_name = str(row.category_name)

        if category_id not in grouped:
            grouped[category_id] = RankingPostsCategoriesResponse(
                category_id=category_id,
                category_name=category_name,
                posts=[],
            )
        # is_time_sale = get_post_sale_flag_map(db, [row.post_id])[row.post_id]
        is_time_sale = bool(sale_map.get(row.post_id, False))
        grouped[category_id].posts.append(
            RankingPostsCategoriesDetailResponse(
                id=str(row.post_id),
                description=row.description,
                thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}"
                if row.thumbnail_key
                else None,
                # likes_count=row.likes_count,
                likes_count=row.purchase_count,
                creator_name=row.profile_name,
                official=row.offical_flg if hasattr(row, "offical_flg") else False,
                username=row.username,
                creator_avatar_url=f"{BASE_URL}/{row.avatar_url}"
                if row.avatar_url
                else None,
                rank=0,
                duration=get_video_duration(row.duration_sec)
                if row.post_type == PostType.VIDEO and row.duration_sec
                else ("画像" if row.post_type == PostType.IMAGE else ""),
                is_time_sale=is_time_sale,
            )
        )

    # sort + set rank
    categories = list[RankingPostsCategoriesResponse](grouped.values())

    if period == "all_time":
        for category in categories:
            category.posts = sorted(
                category.posts, key=lambda x: x.likes_count or 0, reverse=True
            )
            for idx, post in enumerate(category.posts):
                post.rank = idx + 1
        return categories

    if period == "monthly":
        for category in categories:
            tracking = [str(x.id) for x in category.posts]
            if len(category.posts) < 6:
                rows_all_time, sale_map_all_time = get_ranking_posts_detail_categories(
                    db, category.category_id, 1, 100, period="all_time"
                )
                idx = 0

                for row in rows_all_time:
                    if str(row.post_id) in tracking:
                        continue
                    if len(category.posts) < 6:
                        post = RankingPostsCategoriesDetailResponse(
                            id=str(row.post_id),
                            description=row.description,
                            thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}"
                            if row.thumbnail_key
                            else None,
                            # likes_count=row.likes_count,
                            likes_count=idx - 1,
                            creator_name=row.profile_name,
                            official=row.offical_flg
                            if hasattr(row, "offical_flg")
                            else False,
                            username=row.username,
                            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}"
                            if row.avatar_url
                            else None,
                            rank=0,
                            duration=get_video_duration(row.duration_sec)
                            if row.post_type == PostType.VIDEO and row.duration_sec
                            else ("画像" if row.post_type == PostType.IMAGE else ""),
                            is_time_sale=bool(
                                sale_map_all_time.get(row.post_id, False)
                            ),
                        )
                        category.posts.append(post)
                        tracking.append(str(row.post_id))
                        idx = idx - 1
                    else:
                        break

        for category in categories:
            category.posts = sorted(
                category.posts, key=lambda x: x.likes_count or 0, reverse=True
            )
            for idx, post in enumerate(category.posts):
                post.rank = idx + 1
        return categories

    if period == "weekly":
        for category in categories:
            tracking = [str(x.id) for x in category.posts]
            if len(category.posts) < 6:
                rows_all_time, sale_map_all_time = get_ranking_posts_detail_categories(
                    db, category.category_id, 1, 100, period="all_time"
                )
                rows_monthly, sale_map_monthly = get_ranking_posts_detail_categories(
                    db, category.category_id, 1, 100, period="monthly"
                )
                idx = 0
                for row in rows_monthly:
                    if str(row.post_id) in tracking:
                        continue
                    if len(category.posts) < 6:
                        post = RankingPostsCategoriesDetailResponse(
                            id=str(row.post_id),
                            description=row.description,
                            thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}"
                            if row.thumbnail_key
                            else None,
                            # likes_count=row.likes_count,
                            likes_count=idx - 1,
                            creator_name=row.profile_name,
                            official=row.offical_flg
                            if hasattr(row, "offical_flg")
                            else False,
                            username=row.username,
                            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}"
                            if row.avatar_url
                            else None,
                            rank=0,
                            duration=get_video_duration(row.duration_sec)
                            if row.post_type == PostType.VIDEO and row.duration_sec
                            else ("画像" if row.post_type == PostType.IMAGE else ""),
                            is_time_sale=bool(sale_map_monthly.get(row.post_id, False)),
                        )
                        category.posts.append(post)
                        tracking.append(str(row.post_id))
                        idx = idx - 1
                    else:
                        break

                for row in rows_all_time:
                    if str(row.post_id) in tracking:
                        continue
                    if len(category.posts) < 6:
                        post = RankingPostsCategoriesDetailResponse(
                            id=str(row.post_id),
                            description=row.description,
                            thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}"
                            if row.thumbnail_key
                            else None,
                            # likes_count=row.likes_count,
                            likes_count=idx - 1,
                            creator_name=row.profile_name,
                            official=row.offical_flg
                            if hasattr(row, "offical_flg")
                            else False,
                            username=row.username,
                            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}"
                            if row.avatar_url
                            else None,
                            rank=0,
                            duration=get_video_duration(row.duration_sec)
                            if row.post_type == PostType.VIDEO and row.duration_sec
                            else ("画像" if row.post_type == PostType.IMAGE else ""),
                            is_time_sale=bool(
                                sale_map_all_time.get(row.post_id, False)
                            ),
                        )
                        category.posts.append(post)
                        tracking.append(str(row.post_id))
                        idx = idx - 1
                    else:
                        break

        for category in categories:
            category.posts = sorted(
                category.posts, key=lambda x: x.likes_count or 0, reverse=True
            )
            for idx, post in enumerate(category.posts):
                post.rank = idx + 1
        return categories

    if period == "daily":
        for category in categories:
            tracking = [str(x.id) for x in category.posts]
            if len(category.posts) < 6:
                rows_all_time, sale_map_all_time = get_ranking_posts_detail_categories(
                    db, category.category_id, 1, 100, period="all_time"
                )
                rows_monthly, sale_map_monthly = get_ranking_posts_detail_categories(
                    db, category.category_id, 1, 100, period="monthly"
                )
                rows_weekly, sale_map_weekly = get_ranking_posts_detail_categories(
                    db, category.category_id, 1, 100, period="weekly"
                )
                idx = 0
                for row in rows_weekly:
                    if str(row.post_id) in tracking:
                        continue
                    if len(category.posts) < 6:
                        post = RankingPostsCategoriesDetailResponse(
                            id=str(row.post_id),
                            description=row.description,
                            thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}"
                            if row.thumbnail_key
                            else None,
                            # likes_count=row.likes_count,
                            likes_count=idx - 1,
                            creator_name=row.profile_name,
                            official=row.offical_flg
                            if hasattr(row, "offical_flg")
                            else False,
                            username=row.username,
                            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}"
                            if row.avatar_url
                            else None,
                            rank=0,
                            duration=get_video_duration(row.duration_sec)
                            if row.post_type == PostType.VIDEO and row.duration_sec
                            else ("画像" if row.post_type == PostType.IMAGE else ""),
                            is_time_sale=bool(sale_map_weekly.get(row.post_id, False)),
                        )
                        category.posts.append(post)
                        tracking.append(str(row.post_id))
                        idx = idx - 1
                    else:
                        break

                for row in rows_monthly:
                    if str(row.post_id) in tracking:
                        continue
                    if len(category.posts) < 6:
                        post = RankingPostsCategoriesDetailResponse(
                            id=str(row.post_id),
                            description=row.description,
                            thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}"
                            if row.thumbnail_key
                            else None,
                            # likes_count=row.likes_count,
                            likes_count=idx - 1,
                            creator_name=row.profile_name,
                            official=row.offical_flg
                            if hasattr(row, "offical_flg")
                            else False,
                            username=row.username,
                            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}"
                            if row.avatar_url
                            else None,
                            rank=0,
                            duration=get_video_duration(row.duration_sec)
                            if row.post_type == PostType.VIDEO and row.duration_sec
                            else ("画像" if row.post_type == PostType.IMAGE else ""),
                            is_time_sale=bool(sale_map_monthly.get(row.post_id, False)),
                        )
                        category.posts.append(post)
                        tracking.append(str(row.post_id))
                        idx = idx - 1
                    else:
                        break

                for row in rows_all_time:
                    if str(row.post_id) in tracking:
                        continue
                    if len(category.posts) < 6:
                        post = RankingPostsCategoriesDetailResponse(
                            id=str(row.post_id),
                            description=row.description,
                            thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}"
                            if row.thumbnail_key
                            else None,
                            # likes_count=row.likes_count,
                            likes_count=idx - 1,
                            creator_name=row.profile_name,
                            official=row.offical_flg
                            if hasattr(row, "offical_flg")
                            else False,
                            username=row.username,
                            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}"
                            if row.avatar_url
                            else None,
                            rank=0,
                            duration=get_video_duration(row.duration_sec)
                            if row.post_type == PostType.VIDEO and row.duration_sec
                            else ("画像" if row.post_type == PostType.IMAGE else ""),
                            is_time_sale=bool(
                                sale_map_all_time.get(row.post_id, False)
                            ),
                        )
                        category.posts.append(post)
                        tracking.append(str(row.post_id))
                        idx = idx - 1
                    else:
                        break

        for category in categories:
            category.posts = sorted(
                category.posts, key=lambda x: x.likes_count or 0, reverse=True
            )
            for idx, post in enumerate(category.posts):
                post.rank = idx + 1
        return categories


@router.get("/posts/detail")
async def get_ranking_posts_detail(
    category: str = Query(..., description="Type is categories"),
    term: str = Query(
        ...,
        description="Terms is terms example is 'all_time', 'monthly', 'weekly', 'daily'",
    ),
    page: int = 1,
    per_page: int = 100,
    db: Session = Depends(get_db),
):
    """
    Get ranking posts detail

    Args:
        db: Database session
        page: Page number
        per_page: Number of items per page
        term: Term is term example is 'all_time', 'monthly', 'weekly', 'daily'
    Returns:
        RankingOverallResponse: Ranking posts
    """
    if page < 1:
        raise HTTPException(
            status_code=400, detail="ページ番号は1以上である必要があります"
        )
    if per_page < 1 or per_page > 100:
        raise HTTPException(
            status_code=400, detail="1ページあたりの件数は1〜100である必要があります"
        )
    try:
        if category == "overall":
            return _get_ranking_posts_overall_detail(db, page, per_page, term)
        else:
            return _get_ranking_posts_categories_detail(
                db, category, page, per_page, term
            )
    except Exception as e:
        logger.error("エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


def _get_ranking_posts_overall_detail(
    db: Session, page: int, per_page: int, term: str
) -> RankingOverallResponse | HTTPException:
    """
    Get overall ranking posts detail

    Args:
        db: Database session
        page: Page number
        per_page: Number of items per page
        terms: Terms is terms example is 'all_time', 'monthly', 'weekly', 'daily'
    Returns:
        RankingOverallResponse: Ranking posts
    """
    if term == "all_time":
        result = get_ranking_posts_detail_overall(db, page, per_page, period="all_time")
    elif term == "monthly":
        result = get_ranking_posts_detail_overall(db, page, per_page, period="monthly")
    elif term == "weekly":
        result = get_ranking_posts_detail_overall(db, page, per_page, period="weekly")
    elif term == "daily":
        result = get_ranking_posts_detail_overall(db, page, per_page, period="daily")
    else:
        raise HTTPException(status_code=400, detail="Invalid terms")

    next_page, previous_page, has_next, has_previous = __process_pagination(
        result, page, per_page
    )

    return RankingPostsDetailResponse(
        posts=[
            RankingPostsDetailDailyResponse(
                id=str(post.Posts.id),
                description=post.Posts.description,
                thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}"
                if post.thumbnail_key
                else None,
                # likes_count=post.likes_count,
                likes_count=0,
                creator_name=post.profile_name,
                official=post.offical_flg if hasattr(post, "offical_flg") else False,
                username=post.username,
                creator_avatar_url=f"{BASE_URL}/{post.avatar_url}"
                if post.avatar_url
                else None,
                rank=idx + ((page - 1) * per_page) + 1,
                duration=get_video_duration(post.duration_sec)
                if post.Posts.post_type == PostType.VIDEO and post.duration_sec
                else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
                is_time_sale=post.Posts.is_time_sale,
            )
            for idx, post in enumerate(result)
        ],
        next_page=next_page,
        previous_page=previous_page,
        has_next=has_next,
        has_previous=has_previous,
    )


def _get_ranking_posts_categories_detail(
    db: Session, category: str, page: int, per_page: int, term: str
) -> RankingCategoriesResponse | HTTPException:
    """
    Get categories ranking posts detail

    Args:
        db: Database session
        category: Category is category_id
        page: Page number
        per_page: Number of items per page
        term: Term is term example is 'all_time', 'monthly', 'weekly', 'daily'
    Returns:
        RankingCategoriesResponse: Ranking posts
    """
    if term == "all_time":
        result, post_sale_map = get_ranking_posts_detail_categories(
            db, category, page, per_page, period="all_time"
        )
    elif term == "monthly":
        result, post_sale_map = get_ranking_posts_detail_categories(
            db, category, page, per_page, period="monthly"
        )
    elif term == "weekly":
        result, post_sale_map = get_ranking_posts_detail_categories(
            db, category, page, per_page, period="weekly"
        )
    elif term == "daily":
        result, post_sale_map = get_ranking_posts_detail_categories(
            db, category, page, per_page, period="daily"
        )
    else:
        raise HTTPException(status_code=400, detail="Invalid terms")

    next_page, previous_page, has_next, has_previous = __process_pagination(
        result, page, per_page
    )

    responsePosts = []
    for idx, row in enumerate(result):
        if not row.profile_name or not row.username:
            continue
        responsePosts.append(
            RankingPostsDetailDailyResponse(
                id=str(row.post_id),
                description=row.description,
                thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}"
                if row.thumbnail_key
                else None,
                # likes_count=row.likes_count,
                likes_count=row.purchase_count,
                creator_name=row.profile_name,
                official=row.offical_flg if hasattr(row, "offical_flg") else False,
                username=row.username,
                creator_avatar_url=f"{BASE_URL}/{row.avatar_url}"
                if row.avatar_url
                else None,
                rank=0,
                duration=get_video_duration(row.duration_sec)
                if row.post_type == PostType.VIDEO and row.duration_sec
                else ("画像" if row.post_type == PostType.IMAGE else ""),
                is_time_sale=bool(post_sale_map.get(row.post_id, False)),
            )
        )
    responsePosts = sorted(responsePosts, key=lambda x: x.likes_count, reverse=True)

    for idx, post in enumerate(responsePosts):
        post.rank = idx + ((page - 1) * per_page) + 1

    return RankingPostsDetailResponse(
        posts=responsePosts,
        next_page=next_page,
        previous_page=previous_page,
        has_next=has_next,
        has_previous=has_previous,
    )


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


@router.get("/creators")
async def get_ranking_creators(
    type: str = Query(..., description="Type, allowed values: overall, categories"),
    current_user: Users = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    if type == "overall":
        return _get_ranking_creators_overall(db, current_user)
    elif type == "categories":
        return _get_ranking_creators_categories(db, current_user)
    else:
        raise HTTPException(status_code=400, detail="Invalid type")


def _get_ranking_creators_overall(
    db: Session, current_user: Users | None
) -> RankingCreatorsResponse:
    """
    Get ranking creators
    """
    try:
        # ranking_creators_all_time = get_ranking_creators_overall_all_time(
        #     db, limit=10, current_user=current_user
        # )
        # ranking_creators_daily = get_ranking_creators_overall_daily(
        #     db, limit=10, current_user=current_user
        # )
        # ranking_creators_weekly = get_ranking_creators_overall_weekly(
        #     db, limit=10, current_user=current_user
        # )
        # ranking_creators_monthly = get_ranking_creators_overall_monthly(
        #     db, limit=10, current_user=current_user
        # )
        ranking_creators_all_time = get_ranking_creators_overall(
            db, limit=10, current_user=current_user, period="all_time"
        )
        ranking_creators_daily = get_ranking_creators_overall(
            db, limit=10, current_user=current_user, period="daily"
        )
        ranking_creators_weekly = get_ranking_creators_overall(
            db, limit=10, current_user=current_user, period="weekly"
        )
        ranking_creators_monthly = get_ranking_creators_overall(
            db, limit=10, current_user=current_user, period="monthly"
        )
        return RankingCreatorsResponse(
            all_time=[
                RankingCreators(
                    id=str(creator.Users.id),
                    name=creator.Users.profile_name,
                    username=creator.username,
                    official=creator.Users.offical_flg
                    if hasattr(creator.Users, "offical_flg")
                    else False,
                    avatar=f"{BASE_URL}/{creator.avatar_url}"
                    if creator.avatar_url
                    else None,
                    cover=f"{BASE_URL}/{creator.cover_url}"
                    if creator.cover_url
                    else None,
                    followers=creator.followers_count or 0,
                    likes=creator.likes_count or 0,
                    follower_ids=[str(current_user.id)]
                    if current_user and creator.is_following
                    else [],
                    rank=idx + 1,
                )
                for idx, creator in enumerate(ranking_creators_all_time)
            ],
            monthly=[
                RankingCreators(
                    id=str(creator.Users.id),
                    name=creator.Users.profile_name,
                    username=creator.username,
                    official=creator.Users.offical_flg
                    if hasattr(creator.Users, "offical_flg")
                    else False,
                    avatar=f"{BASE_URL}/{creator.avatar_url}"
                    if creator.avatar_url
                    else None,
                    cover=f"{BASE_URL}/{creator.cover_url}"
                    if creator.cover_url
                    else None,
                    followers=creator.followers_count or 0,
                    likes=creator.likes_count or 0,
                    follower_ids=[str(current_user.id)]
                    if current_user and creator.is_following
                    else [],
                    rank=idx + 1,
                )
                for idx, creator in enumerate(ranking_creators_monthly)
            ],
            weekly=[
                RankingCreators(
                    id=str(creator.Users.id),
                    name=creator.Users.profile_name,
                    username=creator.username,
                    official=creator.Users.offical_flg
                    if hasattr(creator.Users, "offical_flg")
                    else False,
                    avatar=f"{BASE_URL}/{creator.avatar_url}"
                    if creator.avatar_url
                    else None,
                    cover=f"{BASE_URL}/{creator.cover_url}"
                    if creator.cover_url
                    else None,
                    followers=creator.followers_count or 0,
                    likes=creator.likes_count or 0,
                    follower_ids=[str(current_user.id)]
                    if current_user and creator.is_following
                    else [],
                    rank=idx + 1,
                )
                for idx, creator in enumerate(ranking_creators_weekly)
            ],
            daily=[
                RankingCreators(
                    id=str(creator.Users.id),
                    name=creator.Users.profile_name,
                    username=creator.username,
                    official=creator.Users.offical_flg
                    if hasattr(creator.Users, "offical_flg")
                    else False,
                    avatar=f"{BASE_URL}/{creator.avatar_url}"
                    if creator.avatar_url
                    else None,
                    cover=f"{BASE_URL}/{creator.cover_url}"
                    if creator.cover_url
                    else None,
                    followers=creator.followers_count or 0,
                    likes=creator.likes_count or 0,
                    follower_ids=[str(current_user.id)]
                    if current_user and creator.is_following
                    else [],
                    rank=idx + 1,
                )
                for idx, creator in enumerate(ranking_creators_daily)
            ],
        )
    except Exception as e:
        logger.error("エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


def _get_ranking_creators_categories(db: Session, current_user: Users | None):
    """
    Get ranking creators categories
    """
    ranking_creators_all_time = get_ranking_creators_categories_overall(
        db, limit_per_category=10, current_user=current_user, period="all_time"
    )
    ranking_creators_daily = get_ranking_creators_categories_overall(
        db, limit_per_category=10, current_user=current_user, period="daily"
    )
    ranking_creators_weekly = get_ranking_creators_categories_overall(
        db, limit_per_category=10, current_user=current_user, period="weekly"
    )
    ranking_creators_monthly = get_ranking_creators_categories_overall(
        db, limit_per_category=10, current_user=current_user, period="monthly"
    )

    return RankingCreatorsCategoriesResponse(
        all_time=__arrange_ranking_creators_categories(
            ranking_creators_all_time, current_user
        ),
        daily=__arrange_ranking_creators_categories(
            ranking_creators_daily, current_user
        ),
        weekly=__arrange_ranking_creators_categories(
            ranking_creators_weekly, current_user
        ),
        monthly=__arrange_ranking_creators_categories(
            ranking_creators_monthly, current_user
        ),
    )


def __arrange_ranking_creators_categories(
    ranking_creators_categories: list, current_user: Users | None
) -> dict:
    grouped: dict[str, RankingCreatorsCategories] = {}
    for row in ranking_creators_categories:
        category_id = str(row.category_id)
        category_name = str(row.category_name)
        if category_id not in grouped:
            grouped[category_id] = RankingCreatorsCategories(
                category_id=category_id,
                category_name=category_name,
                creators=[],
            )
        grouped[category_id].creators.append(
            RankingCreators(
                id=str(row.creator_user_id),
                name=row.profile_name,
                username=row.username,
                official=row.offical_flg if hasattr(row, "offical_flg") else False,
                avatar=f"{BASE_URL}/{row.avatar_url}" if row.avatar_url else None,
                cover=f"{BASE_URL}/{row.cover_url}" if row.cover_url else None,
                followers=row.followers_count or 0,
                likes=row.likes_count or 0,
                follower_ids=[str(current_user.id)]
                if current_user and row.is_following
                else [],
                rank=0,
            )
        )

    categories = list[RankingCreatorsCategories](grouped.values())
    for category in categories:
        category.creators = sorted(
            category.creators, key=lambda x: x.likes, reverse=True
        )
        for idx, creator in enumerate(category.creators):
            creator.rank = idx + 1

    return categories


@router.get("/creators/detail")
async def get_ranking_creators_detail(
    category: str = Query(..., description="Type is categories"),
    term: str = Query(
        ...,
        description="Terms is terms example is 'all_time', 'monthly', 'weekly', 'daily'",
    ),
    page: int = 1,
    per_page: int = 100,
    db: Session = Depends(get_db),
    current_user: Users = Depends(get_current_user_optional),
):
    if page < 1:
        raise HTTPException(
            status_code=400, detail="ページ番号は1以上である必要があります"
        )
    if per_page < 1 or per_page > 100:
        raise HTTPException(
            status_code=400, detail="1ページあたりの件数は1〜100である必要があります"
        )
    if category == "overall":
        return _get_ranking_creators_detail_overall(
            db, term, page, per_page, current_user
        )
    else:
        return _get_ranking_creators_detail_categories(
            db, category, term, page, per_page, current_user
        )


def _get_ranking_creators_detail_overall(
    db: Session, term: str, page: int, per_page: int, current_user: Users | None
) -> RankingCreatorsDetailResponse:
    """
    Get ranking creators detail overall
    """
    try:
        # result = get_ranking_creators_overall_detail_overall(
        #     db, page, per_page, term, current_user
        # )
        result = get_ranking_creators_overall(
            db, page=page, limit=per_page, current_user=current_user, period=term
        )
        next_page, previous_page, has_next, has_previous = __process_pagination(
            result, page, per_page
        )
        return RankingCreatorsDetailResponse(
            creators=[
                RankingCreators(
                    id=str(creator.Users.id),
                    name=creator.Users.profile_name,
                    username=creator.username,
                    official=creator.Users.offical_flg
                    if hasattr(creator.Users, "offical_flg")
                    else False,
                    avatar=f"{BASE_URL}/{creator.avatar_url}"
                    if creator.avatar_url
                    else None,
                    cover=f"{BASE_URL}/{creator.cover_url}"
                    if creator.cover_url
                    else None,
                    followers=creator.followers_count or 0,
                    likes=creator.likes_count or 0,
                    follower_ids=[str(current_user.id)]
                    if current_user and creator.is_following
                    else [],
                    rank=idx + ((page - 1) * per_page) + 1,
                )
                for idx, creator in enumerate(result)
            ],
            next_page=next_page,
            previous_page=previous_page,
            has_next=has_next,
            has_previous=has_previous,
        )
    except Exception as e:
        logger.error("エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))


def _get_ranking_creators_detail_categories(
    db: Session,
    category: str,
    term: str,
    page: int,
    per_page: int,
    current_user: Users | None,
) -> RankingCreatorsDetailResponse:
    """
    Get ranking creators detail categories
    """
    try:
        result = get_ranking_creators_categories_detail(
            db, category, page, per_page, term, current_user=current_user
        )
        next_page, previous_page, has_next, has_previous = __process_pagination(
            result, page, per_page
        )
        return RankingCreatorsDetailResponse(
            creators=[
                RankingCreators(
                    id=str(creator.Users.id),
                    name=creator.Users.profile_name,
                    username=creator.username,
                    official=creator.Users.offical_flg
                    if hasattr(creator.Users, "offical_flg")
                    else False,
                    avatar=f"{BASE_URL}/{creator.avatar_url}"
                    if creator.avatar_url
                    else None,
                    cover=f"{BASE_URL}/{creator.cover_url}"
                    if creator.cover_url
                    else None,
                    followers=creator.followers_count or 0,
                    likes=creator.likes_count or 0,
                    follower_ids=[str(current_user.id)]
                    if current_user and creator.is_following
                    else [],
                    rank=idx + ((page - 1) * per_page) + 1,
                )
                for idx, creator in enumerate(result)
            ],
            next_page=next_page,
            previous_page=previous_page,
            has_next=has_next,
            has_previous=has_previous,
        )
    except Exception as e:
        logger.error("エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))
