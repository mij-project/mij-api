from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.api.commons.utils import get_video_duration
from app.constants.enums import PostType
from app.db.base import get_db
from app.crud.creater_crud import (
    get_ranking_creators_categories_detail,
    get_ranking_creators_categories_overall_all_time,
    get_ranking_creators_categories_overall_daily,
    get_ranking_creators_categories_overall_monthly,
    get_ranking_creators_categories_overall_weekly,
    get_ranking_creators_overall_all_time,
    get_ranking_creators_overall_daily,
    get_ranking_creators_overall_detail_overall,
    get_ranking_creators_overall_monthly,
    get_ranking_creators_overall_weekly,

)
from app.crud.post_crud import (
    get_ranking_posts_categories_all_time,
    get_ranking_posts_categories_daily,
    get_ranking_posts_categories_monthly,
    get_ranking_posts_categories_weekly,
    get_ranking_posts_detail_categories_all_time,
    get_ranking_posts_detail_categories_daily,
    get_ranking_posts_detail_categories_monthly,
    get_ranking_posts_detail_categories_weekly,
    get_ranking_posts_detail_overall_all_time,
    get_ranking_posts_detail_overall_daily,
    get_ranking_posts_detail_overall_monthly,
    get_ranking_posts_detail_overall_weekly,
    get_ranking_posts_overall_all_time,
    get_ranking_posts_overall_monthly,
    get_ranking_posts_overall_weekly,
    get_ranking_posts_overall_daily
)
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
        logger.error('エラーが発生しました', e)
        raise HTTPException(status_code=500, detail=str(e))

def _get_ranking_posts_overall(db: Session) -> RankingOverallResponse:
    """
        Get overall ranking posts

        Args:
            db: Database session
        Returns:
            RankingResponse: Ranking posts
    """
    ranking_posts_all_time = get_ranking_posts_overall_all_time(db, limit=5)
    ranking_posts_monthly = get_ranking_posts_overall_monthly(db, limit=5)
    ranking_posts_weekly = get_ranking_posts_overall_weekly(db, limit=5)
    ranking_posts_daily = get_ranking_posts_overall_daily(db, limit=5)
    
    return RankingOverallResponse(
        all_time=[RankingPostsAllTimeResponse(
            id=str(post.Posts.id),  # UUIDを文字列に変換
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            official=post.offical_flg if hasattr(post, 'offical_flg') else False,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + 1,
            duration=get_video_duration(post.duration_sec) if post.Posts.post_type == PostType.VIDEO and post.duration_sec else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
        ) for idx, post in enumerate(ranking_posts_all_time)],
        monthly=[RankingPostsMonthlyResponse(
            id=str(post.Posts.id),  # UUIDを文字列に変換
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            official=post.offical_flg if hasattr(post, 'offical_flg') else False,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + 1,
            duration=get_video_duration(post.duration_sec) if post.Posts.post_type == PostType.VIDEO and post.duration_sec else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
        ) for idx, post in enumerate(ranking_posts_monthly)],
        weekly=[RankingPostsWeeklyResponse(
            id=str(post.Posts.id),  # UUIDを文字列に変換
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            official=post.offical_flg if hasattr(post, 'offical_flg') else False,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + 1,
            duration=get_video_duration(post.duration_sec) if post.Posts.post_type == PostType.VIDEO and post.duration_sec else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
        ) for idx, post in enumerate(ranking_posts_weekly)],
        daily=[RankingPostsDailyResponse(
            id=str(post.Posts.id),  # UUIDを文字列に変換
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            official=post.offical_flg if hasattr(post, 'offical_flg') else False,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + 1,
            duration=get_video_duration(post.duration_sec) if post.Posts.post_type == PostType.VIDEO and post.duration_sec else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
        ) for idx, post in enumerate(ranking_posts_daily)],
    )

def _get_ranking_posts_categories(db: Session) -> RankingCategoriesResponse:
    """
        Get categories ranking posts

        Args:
            db: Database session
        Returns:
            RankingCategoriesResponse: Ranking posts
    """
    ranking_posts_categories_all_time = get_ranking_posts_categories_all_time(db, limit=5)
    ranking_posts_categories_daily = get_ranking_posts_categories_daily(db, limit=5)
    ranking_posts_categories_weekly = get_ranking_posts_categories_weekly(db, limit=5)
    ranking_posts_categories_monthly = get_ranking_posts_categories_monthly(db, limit=5)
    
    response = {
        "all_time": __arrange_ranking_posts_categories(ranking_posts_categories_all_time),
        "daily": __arrange_ranking_posts_categories(ranking_posts_categories_daily),
        "weekly": __arrange_ranking_posts_categories(ranking_posts_categories_weekly),
        "monthly": __arrange_ranking_posts_categories(ranking_posts_categories_monthly),
    }
    return RankingCategoriesResponse(
        all_time=response["all_time"],
        daily=response["daily"],
        weekly=response["weekly"],
        monthly=response["monthly"],
    )

def __arrange_ranking_posts_categories(ranking_posts_categories: list) -> dict:
    grouped: dict[str, RankingPostsCategoriesResponse] = {}

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

        grouped[category_id].posts.append(
            RankingPostsCategoriesDetailResponse(
                id=str(row.post_id),
                description=row.description,
                thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}" if row.thumbnail_key else None,
                likes_count=row.likes_count,
                creator_name=row.profile_name,
                official=row.offical_flg if hasattr(row, 'offical_flg') else False,
                username=row.username,
                creator_avatar_url=f"{BASE_URL}/{row.avatar_url}" if row.avatar_url else None,
                rank=0,
                duration=get_video_duration(row.duration_sec) if row.post_type == PostType.VIDEO and row.duration_sec else ("画像" if row.post_type == PostType.IMAGE else ""),
            )
        )

    # sort + set rank
    categories = list[RankingPostsCategoriesResponse](grouped.values())
    for category in categories:
        category.posts = sorted(category.posts, key=lambda x: x.likes_count or 0, reverse=True)
        for idx, post in enumerate(category.posts):
            post.rank = idx + 1

    return categories


@router.get("/posts/detail")   
async def get_ranking_posts_detail(
    category: str = Query(..., description="Type is categories"),
    term: str = Query(..., description="Terms is terms example is 'all_time', 'monthly', 'weekly', 'daily'"),
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
        raise HTTPException(status_code=400, detail="ページ番号は1以上である必要があります")
    if per_page < 1 or per_page > 100:
        raise HTTPException(status_code=400, detail="1ページあたりの件数は1〜100である必要があります")
    try:
        if category == "overall":
            return _get_ranking_posts_overall_detail(db, page, per_page, term)
        else:
            return _get_ranking_posts_categories_detail(db, category, page, per_page, term)
    except Exception as e:
        logger.error("エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

def _get_ranking_posts_overall_detail(db: Session, page: int, per_page: int, term: str) -> RankingOverallResponse | HTTPException:
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
        result = get_ranking_posts_detail_overall_all_time(db, page, per_page)
    elif term == "monthly":
        result =  get_ranking_posts_detail_overall_monthly(db, page, per_page)
    elif term == "weekly":
        result =  get_ranking_posts_detail_overall_weekly(db, page, per_page)
    elif term == "daily":
        result =  get_ranking_posts_detail_overall_daily(db, page, per_page)
    else:
        raise HTTPException(status_code=400, detail="Invalid terms")

    next_page, previous_page, has_next, has_previous = __process_pagination(result, page, per_page)

    return RankingPostsDetailResponse(
        posts=[RankingPostsDetailDailyResponse(
            id=str(post.Posts.id),
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            official=post.offical_flg if hasattr(post, 'offical_flg') else False,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + ((page -1) * per_page) + 1,
            duration=get_video_duration(post.duration_sec) if post.Posts.post_type == PostType.VIDEO and post.duration_sec else ("画像" if post.Posts.post_type == PostType.IMAGE else ""),
        ) for idx, post in enumerate(result)],
        next_page=next_page,
        previous_page=previous_page,
        has_next=has_next,
        has_previous=has_previous
    )

def _get_ranking_posts_categories_detail(db: Session, category: str, page: int, per_page: int, term: str) -> RankingCategoriesResponse | HTTPException:
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
        result = get_ranking_posts_detail_categories_all_time(db, category, page, per_page)
    elif term == "monthly":
        result = get_ranking_posts_detail_categories_monthly(db, category, page, per_page)
    elif term == "weekly":
        result = get_ranking_posts_detail_categories_weekly(db, category, page, per_page)
    elif term == "daily":
        result = get_ranking_posts_detail_categories_daily(db, category, page, per_page)
    else:
        raise HTTPException(status_code=400, detail="Invalid terms")
    
    next_page, previous_page, has_next, has_previous = __process_pagination(result, page, per_page)

    responsePosts = []
    for idx, row in enumerate(result):
        if not row.profile_name or not row.username:
            continue
        responsePosts.append(RankingPostsDetailDailyResponse(
            id=str(row.post_id),
            description=row.description,
            thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}" if row.thumbnail_key else None,
            likes_count=row.likes_count,
            creator_name=row.profile_name,
            official=row.offical_flg if hasattr(row, 'offical_flg') else False,
            username=row.username,
            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}" if row.avatar_url else None,
            rank=0,
            duration=get_video_duration(row.duration_sec) if row.post_type == PostType.VIDEO and row.duration_sec else ("画像" if row.post_type == PostType.IMAGE else ""),
        ))
    responsePosts = sorted(responsePosts, key=lambda x: x.likes_count, reverse=True)
    
    for idx, post in enumerate(responsePosts):
        post.rank = idx + ((page -1) * per_page) + 1

    return RankingPostsDetailResponse(
        posts=responsePosts,
        next_page=next_page,
        previous_page=previous_page,
        has_next=has_next,
        has_previous=has_previous
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
    db: Session = Depends(get_db),
):
    if type == "overall":
        return _get_ranking_creators_overall(db)
    elif type == "categories":
        return _get_ranking_creators_categories(db)
    else:
        raise HTTPException(status_code=400, detail="Invalid type")

def _get_ranking_creators_overall(db: Session) -> RankingCreatorsResponse:
    """
        Get ranking creators
    """
    try:
        ranking_creators_all_time = get_ranking_creators_overall_all_time(db, limit=10)
        ranking_creators_daily = get_ranking_creators_overall_daily(db, limit=10)
        ranking_creators_weekly = get_ranking_creators_overall_weekly(db, limit=10)
        ranking_creators_monthly = get_ranking_creators_overall_monthly(db, limit=10)
        return RankingCreatorsResponse(
            all_time=[RankingCreators( 
                id=str(creator.Users.id),
                name=creator.Users.profile_name,
                username=creator.username,
                official=creator.Users.offical_flg if hasattr(creator.Users, 'offical_flg') else False,
                avatar=f"{BASE_URL}/{creator.avatar_url}" if creator.avatar_url else None,
                cover=f"{BASE_URL}/{creator.cover_url}" if creator.cover_url else None,
                followers=creator.followers_count,
                likes=creator.likes_count,
                follower_ids=creator.follower_ids,
                rank=idx + 1
            ) for idx, creator in enumerate(ranking_creators_all_time)], 
            monthly=[RankingCreators( 
                id=str(creator.Users.id),
                name=creator.Users.profile_name,
                username=creator.username,
                official=creator.Users.offical_flg if hasattr(creator.Users, 'offical_flg') else False,
                avatar=f"{BASE_URL}/{creator.avatar_url}" if creator.avatar_url else None,
                cover=f"{BASE_URL}/{creator.cover_url}" if creator.cover_url else None,
                followers=creator.followers_count,
                likes=creator.likes_count,
                follower_ids=creator.follower_ids,
                rank=idx + 1
            ) for idx, creator in enumerate(ranking_creators_monthly)],
            weekly=[RankingCreators( 
                id=str(creator.Users.id),
                name=creator.Users.profile_name,
                username=creator.username,
                official=creator.Users.offical_flg if hasattr(creator.Users, 'offical_flg') else False,
                avatar=f"{BASE_URL}/{creator.avatar_url}" if creator.avatar_url else None,
                cover=f"{BASE_URL}/{creator.cover_url}" if creator.cover_url else None,
                followers=creator.followers_count,
                likes=creator.likes_count,
                follower_ids=creator.follower_ids,
                rank=idx + 1
            ) for idx, creator in enumerate(ranking_creators_weekly)],
            daily=[RankingCreators( 
                id=str(creator.Users.id),
                name=creator.Users.profile_name,
                username=creator.username,
                official=creator.Users.offical_flg if hasattr(creator.Users, 'offical_flg') else False,
                avatar=f"{BASE_URL}/{creator.avatar_url}" if creator.avatar_url else None,
                cover=f"{BASE_URL}/{creator.cover_url}" if creator.cover_url else None,
                followers=creator.followers_count,
                likes=creator.likes_count,
                follower_ids=creator.follower_ids,
                rank=idx + 1
            ) for idx, creator in enumerate(ranking_creators_daily)],
        )
    except Exception as e:
        logger.error("エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))

def _get_ranking_creators_categories(db: Session):
    """
        Get ranking creators categories
    """
    ranking_creators_all_time = get_ranking_creators_categories_overall_all_time(db, limit=10)
    ranking_creators_daily = get_ranking_creators_categories_overall_daily(db, limit=10)
    ranking_creators_weekly = get_ranking_creators_categories_overall_weekly(db, limit=10)
    ranking_creators_monthly = get_ranking_creators_categories_overall_monthly(db, limit=10)

    return RankingCreatorsCategoriesResponse(
        all_time=__arrange_ranking_creators_categories(ranking_creators_all_time),
        daily=__arrange_ranking_creators_categories(ranking_creators_daily),
        weekly=__arrange_ranking_creators_categories(ranking_creators_weekly),
        monthly=__arrange_ranking_creators_categories(ranking_creators_monthly),
    )

def __arrange_ranking_creators_categories(ranking_creators_categories: list) -> dict:
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
        grouped[category_id].creators.append(RankingCreators(
            id=str(row.creator_user_id),
            name=row.profile_name,
            username=row.username,
            official=row.offical_flg if hasattr(row, 'offical_flg') else False,
            avatar=f"{BASE_URL}/{row.avatar_url}" if row.avatar_url else None,
            cover=f"{BASE_URL}/{row.cover_url}" if row.cover_url else None,
            followers=row.followers_count,
            likes=row.likes_count,
            follower_ids=row.follower_ids,
            rank=0
        ))
    
    categories = list[RankingCreatorsCategories](grouped.values())
    for category in categories:
        category.creators = sorted(category.creators, key=lambda x: x.likes, reverse=True)
        for idx, creator in enumerate(category.creators):
            creator.rank = idx + 1

    return categories

@router.get("/creators/detail")
async def get_ranking_creators_detail(
    category: str = Query(..., description="Type is categories"),
    term: str = Query(..., description="Terms is terms example is 'all_time', 'monthly', 'weekly', 'daily'"),
    page: int = 1,
    per_page: int = 100,
    db: Session = Depends(get_db),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="ページ番号は1以上である必要があります")
    if per_page < 1 or per_page > 100:
        raise HTTPException(status_code=400, detail="1ページあたりの件数は1〜100である必要があります")
    if category == "overall":
        return _get_ranking_creators_detail_overall(db, term, page, per_page)
    else:
        return _get_ranking_creators_detail_categories(db, category, term, page, per_page)

def _get_ranking_creators_detail_overall(db: Session, term: str, page: int, per_page: int) -> RankingCreatorsDetailResponse:
    """
        Get ranking creators detail overall
    """
    try:
        result = get_ranking_creators_overall_detail_overall(db, page, per_page, term)
        next_page, previous_page, has_next, has_previous = __process_pagination(result, page, per_page)
        return RankingCreatorsDetailResponse(
            creators=[RankingCreators(
                id=str(creator.Users.id),
                name=creator.Users.profile_name,
                username=creator.username,
                official=creator.Users.offical_flg if hasattr(creator.Users, 'offical_flg') else False,
                avatar=f"{BASE_URL}/{creator.avatar_url}" if creator.avatar_url else None,
                cover=f"{BASE_URL}/{creator.cover_url}" if creator.cover_url else None,
                followers=creator.followers_count,
                likes=creator.likes_count,
                follower_ids=creator.follower_ids,
                rank=idx + ((page -1) * per_page) + 1
            ) for idx, creator in enumerate(result)],
            next_page=next_page,
            previous_page=previous_page,
            has_next=has_next,
            has_previous=has_previous
        )
    except Exception as e:
        logger.error('エラーが発生しました', e)
        raise HTTPException(status_code=500, detail=str(e))

def _get_ranking_creators_detail_categories(db: Session, category: str, term: str, page: int, per_page: int) -> RankingCreatorsDetailResponse:
    """
        Get ranking creators detail categories
    """
    try:
        result = get_ranking_creators_categories_detail(db, category, page, per_page, term)
        next_page, previous_page, has_next, has_previous = __process_pagination(result, page, per_page)
        return RankingCreatorsDetailResponse(
            creators=[RankingCreators(
                id=str(creator.Users.id),
                name=creator.Users.profile_name,
                username=creator.username,
                official=creator.Users.offical_flg if hasattr(creator.Users, 'offical_flg') else False,
                avatar=f"{BASE_URL}/{creator.avatar_url}" if creator.avatar_url else None,
                cover=f"{BASE_URL}/{creator.cover_url}" if creator.cover_url else None,
                followers=creator.followers_count,
                likes=creator.likes_count,
                follower_ids=creator.follower_ids,
                rank=idx + ((page -1) * per_page) + 1
            ) for idx, creator in enumerate(result)],
            next_page=next_page,
            previous_page=previous_page,
            has_next=has_next,
            has_previous=has_previous
        )
    except Exception as e:
        logger.error("エラーが発生しました", e)
        raise HTTPException(status_code=500, detail=str(e))