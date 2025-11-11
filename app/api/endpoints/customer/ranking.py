from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.crud.post_crud import (
    get_ranking_creators_overall_all_time,
    get_ranking_creators_overall_daily,
    get_ranking_creators_overall_detail_all_time,
    get_ranking_creators_overall_detail_daily,
    get_ranking_creators_overall_detail_monthly,
    get_ranking_creators_overall_detail_weekly,
    get_ranking_creators_overall_monthly,
    get_ranking_creators_overall_weekly,
    get_ranking_posts_detail_genres_all_time,
    get_ranking_posts_detail_genres_daily,
    get_ranking_posts_detail_genres_monthly,
    get_ranking_posts_detail_genres_weekly,
    get_ranking_posts_detail_overall_all_time,
    get_ranking_posts_detail_overall_daily,
    get_ranking_posts_detail_overall_monthly,
    get_ranking_posts_detail_overall_weekly,
    get_ranking_posts_genres_all_time,
    get_ranking_posts_genres_daily,
    get_ranking_posts_genres_monthly,
    get_ranking_posts_genres_weekly,
    get_ranking_posts_overall_all_time,
    get_ranking_posts_overall_monthly,
    get_ranking_posts_overall_weekly,
    get_ranking_posts_overall_daily
)
from app.schemas.ranking import (
    RankingCreators,
    RankingCreatorsDetailResponse,
    RankingCreatorsResponse,
    RankingGenresResponse,
    RankingOverallResponse,
    RankingPostsAllTimeResponse,
    RankingPostsDetailDailyResponse,
    RankingPostsDetailResponse,
    RankingPostsGenresDetailResponse,
    RankingPostsGenresResponse,
    RankingPostsMonthlyResponse,
    RankingPostsWeeklyResponse,
    RankingPostsDailyResponse,
)
from os import getenv

BASE_URL = getenv("CDN_BASE_URL")

router = APIRouter()

@router.get("/posts")   
async def get_ranking_posts(
    type: str = Query(..., description="Type, allowed values: overall, genres"),
    db: Session = Depends(get_db),
):
    try:
        if type == "overall":
            return _get_ranking_posts_overall(db)
        if type == "genres":
            return _get_ranking_posts_genres(db)

    except Exception as e:
        print('エラーが発生しました', e)
        raise HTTPException(status_code=500, detail=str(e))

def _get_ranking_posts_overall(db: Session) -> RankingOverallResponse:
    """
        Get overall ranking posts

        Args:
            db: Database session
        Returns:
            RankingResponse: Ranking posts
    """
    ranking_posts_all_time = get_ranking_posts_overall_all_time(db, limit=10)
    ranking_posts_monthly = get_ranking_posts_overall_monthly(db, limit=10)
    ranking_posts_weekly = get_ranking_posts_overall_weekly(db, limit=10)
    ranking_posts_daily = get_ranking_posts_overall_daily(db, limit=10)
    
    return RankingOverallResponse(
        all_time=[RankingPostsAllTimeResponse(
            id=str(post.Posts.id),  # UUIDを文字列に変換
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + 1
        ) for idx, post in enumerate(ranking_posts_all_time)],
        monthly=[RankingPostsMonthlyResponse(
            id=str(post.Posts.id),  # UUIDを文字列に変換
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + 1
        ) for idx, post in enumerate(ranking_posts_monthly)],
        weekly=[RankingPostsWeeklyResponse(
            id=str(post.Posts.id),  # UUIDを文字列に変換
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + 1
        ) for idx, post in enumerate(ranking_posts_weekly)],
        daily=[RankingPostsDailyResponse(
            id=str(post.Posts.id),  # UUIDを文字列に変換
            description=post.Posts.description,
            thumbnail_url=f"{BASE_URL}/{post.thumbnail_key}" if post.thumbnail_key else None,
            likes_count=post.likes_count,
            creator_name=post.profile_name,
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + 1
        ) for idx, post in enumerate(ranking_posts_daily)],
    )

def _get_ranking_posts_genres(db: Session) -> RankingGenresResponse:
    """
        Get genres ranking posts

        Args:
            db: Database session
        Returns:
            RankingGenresResponse: Ranking posts
    """
    ranking_posts_genres_all_time = get_ranking_posts_genres_all_time(db, limit=10)
    ranking_posts_genres_daily = get_ranking_posts_genres_daily(db, limit=10)
    ranking_posts_genres_weekly = get_ranking_posts_genres_weekly(db, limit=10)
    ranking_posts_genres_monthly = get_ranking_posts_genres_monthly(db, limit=10)
    
    response = {
        "all_time": __arrange_ranking_posts_genres(ranking_posts_genres_all_time),
        "daily": __arrange_ranking_posts_genres(ranking_posts_genres_daily),
        "weekly": __arrange_ranking_posts_genres(ranking_posts_genres_weekly),
        "monthly": __arrange_ranking_posts_genres(ranking_posts_genres_monthly),
    }
    return RankingGenresResponse(
        all_time=response["all_time"],
        daily=response["daily"],
        weekly=response["weekly"],
        monthly=response["monthly"],
    )

def __arrange_ranking_posts_genres(ranking_posts_genres: list) -> dict:
    grouped: dict[str, RankingPostsGenresResponse] = {}

    for row in ranking_posts_genres:
        # bỏ qua post không có creator
        if not row.profile_name:
            continue

        genre_id = str(row.category_id)       # giờ đang group theo category
        genre_name = str(row.category_name)

        if genre_id not in grouped:
            grouped[genre_id] = RankingPostsGenresResponse(
                genre_id=genre_id,
                genre_name=genre_name,
                posts=[],
            )

        grouped[genre_id].posts.append(
            RankingPostsGenresDetailResponse(
                id=str(row.post_id),
                description=row.description,
                thumbnail_url=f"{BASE_URL}/{row.thumbnail_key}" if row.thumbnail_key else None,
                likes_count=row.likes_count,
                creator_name=row.profile_name,
                username=row.username,
                creator_avatar_url=f"{BASE_URL}/{row.avatar_url}" if row.avatar_url else None,
                rank=0,
            )
        )

    # sort + set rank
    results = list(grouped.values())
    for genre in results:
        genre.posts = sorted(genre.posts, key=lambda x: x.likes_count or 0, reverse=True)
        for idx, post in enumerate(genre.posts):
            post.rank = idx + 1

    return results


@router.get("/posts/detail")   
async def get_ranking_posts_detail(
    genre: str = Query(..., description="Type is genres"),
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
        if genre == "overall":
            return _get_ranking_posts_overall_detail(db, page, per_page, term)
        else:
            return _get_ranking_posts_genres_detail(db, genre, page, per_page, term)
    except Exception as e:
        print('エラーが発生しました', e)
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
            username=post.username,
            creator_avatar_url=f"{BASE_URL}/{post.avatar_url}" if post.avatar_url else None,
            rank=idx + ((page -1) * per_page) + 1
        ) for idx, post in enumerate(result)],
        next_page=next_page,
        previous_page=previous_page,
        has_next=has_next,
        has_previous=has_previous
    )

def _get_ranking_posts_genres_detail(db: Session, genre: str, page: int, per_page: int, term: str) -> RankingGenresResponse | HTTPException:
    """
        Get genres ranking posts detail

        Args:
            db: Database session
            genre: Genre is genre_id
            page: Page number
            per_page: Number of items per page
            term: Term is term example is 'all_time', 'monthly', 'weekly', 'daily'
        Returns:
            RankingGenresResponse: Ranking posts
    """
    if term == "all_time":
        result = get_ranking_posts_detail_genres_all_time(db, genre, page, per_page)
    elif term == "monthly":
        result = get_ranking_posts_detail_genres_monthly(db, genre, page, per_page)
    elif term == "weekly":
        result = get_ranking_posts_detail_genres_weekly(db, genre, page, per_page)
    elif term == "daily":
        result = get_ranking_posts_detail_genres_daily(db, genre, page, per_page)
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
            username=row.username,
            creator_avatar_url=f"{BASE_URL}/{row.avatar_url}" if row.avatar_url else None,
            rank=0
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
    db: Session = Depends(get_db),
):
    return _get_ranking_creators(db)

def _get_ranking_creators(db: Session) -> RankingCreatorsResponse:
    """
        Get ranking creators
    """
    try:
        ranking_creators_all_time = get_ranking_creators_overall_all_time(db, limit=20)
        ranking_creators_daily = get_ranking_creators_overall_daily(db, limit=20)
        ranking_creators_weekly = get_ranking_creators_overall_weekly(db, limit=20)
        ranking_creators_monthly = get_ranking_creators_overall_monthly(db, limit=20)
        return RankingCreatorsResponse(
            all_time=[RankingCreators( 
                id=str(creator.Users.id),
                name=creator.Users.profile_name,
                username=creator.username,
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
                avatar=f"{BASE_URL}/{creator.avatar_url}" if creator.avatar_url else None,
                cover=f"{BASE_URL}/{creator.cover_url}" if creator.cover_url else None,
                followers=creator.followers_count,
                likes=creator.likes_count,
                follower_ids=creator.follower_ids,
                rank=idx + 1
            ) for idx, creator in enumerate(ranking_creators_daily)],
        )
    except Exception as e:
        print('エラーが発生しました', e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/creators/detail")
async def get_ranking_creators_detail(
    term: str = Query(..., description="Terms is terms example is 'all_time', 'monthly', 'weekly', 'daily'"),
    page: int = 1,
    per_page: int = 100,
    db: Session = Depends(get_db),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="ページ番号は1以上である必要があります")
    if per_page < 1 or per_page > 100:
        raise HTTPException(status_code=400, detail="1ページあたりの件数は1〜100である必要があります")

    return _get_ranking_creators_detail(db, term, page, per_page)

def _get_ranking_creators_detail(db: Session, term: str, page: int, per_page: int) -> RankingCreatorsDetailResponse:
    """
        Get ranking creators detail
    """
    try:
        if term == "all_time":
            result = get_ranking_creators_overall_detail_all_time(db, page, per_page)
        elif term == "monthly":
            result = get_ranking_creators_overall_detail_monthly(db, page, per_page)
        elif term == "weekly":
            result = get_ranking_creators_overall_detail_weekly(db, page, per_page)
        elif term == "daily":
            result = get_ranking_creators_overall_detail_daily(db, page, per_page)
        else:
            raise HTTPException(status_code=400, detail="Invalid terms")
        next_page, previous_page, has_next, has_previous = __process_pagination(result, page, per_page)
        return RankingCreatorsDetailResponse(
            creators=[RankingCreators(
                id=str(creator.Users.id),
                name=creator.Users.profile_name,
                username=creator.username,
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
        print('エラーが発生しました', e)
        raise HTTPException(status_code=500, detail=str(e))