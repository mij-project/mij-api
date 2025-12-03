from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func, desc, case
from typing import List, Optional, Tuple
from uuid import UUID

from app.models.user import Users
from app.models.profiles import Profiles
from app.models.posts import Posts
from app.models.tags import Tags, PostTags
from app.models.post_categories import PostCategories
from app.models.social import Follows, Likes
from app.models.media_assets import MediaAssets
from app.models.prices import Prices
from app.constants.enums import PostStatus, AccountType, MediaAssetKind


def search_creators(
    db: Session,
    query: str,
    sort: str = "relevance",
    limit: int = 5,
    offset: int = 0,
    include_recent_posts: bool = False,
) -> Tuple[List, int]:
    """
    クリエイター検索

    Args:
        db: データベースセッション
        query: 検索クエリ
        sort: ソート基準 ('relevance' or 'popularity')
        limit: 取得件数
        offset: オフセット
        include_recent_posts: 最新投稿5件を含めるかどうか

    Returns:
        (結果リスト, 総件数)
    """
    # 検索クエリの前処理
    query_lower = query.lower().strip()
    tsquery = func.plainto_tsquery("simple", query)
    now = func.now()
    active_post_cond = and_(
        Posts.deleted_at.is_(None),
        Posts.status == PostStatus.APPROVED,
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    # ベースクエリ
    base_query = (
        db.query(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.bio,
            func.count(Follows.creator_user_id).label("followers_count"),
            Users.is_identity_verified.label("is_verified"),
            func.count(Posts.id).label("posts_count"),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, and_(Users.id == Posts.creator_user_id, active_post_cond))
        .filter(Users.deleted_at.is_(None))
        .filter(Users.role == AccountType.CREATOR)
        .group_by(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.bio,
            Users.is_identity_verified,
        )
    )

    # 検索条件
    search_conditions = or_(
        func.to_tsvector("simple", Users.profile_name).op("@@")(tsquery),
        func.to_tsvector("simple", Profiles.username).op("@@")(tsquery),
        func.to_tsvector("simple", func.coalesce(Profiles.bio, "")).op("@@")(tsquery),
        Users.profile_name.ilike(f"{query_lower}%"),  # 前方一致
        Profiles.username.ilike(f"{query_lower}%"),
    )

    base_query = base_query.filter(search_conditions)

    # 総件数取得（サブクエリで効率化）
    from sqlalchemy import select

    count_query = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_query).scalar()

    # ソート
    if sort == "popularity":
        base_query = base_query.order_by(desc("followers_count"))
    else:  # relevance
        # スコアリング: 完全一致 > 前方一致 > 部分一致
        relevance_score = case(
            (Users.profile_name.ilike(query_lower), 10.0),
            (Profiles.username.ilike(query_lower), 10.0),
            (Users.profile_name.ilike(f"{query_lower}%"), 5.0),
            (Profiles.username.ilike(f"{query_lower}%"), 5.0),
            else_=func.ts_rank(func.to_tsvector("simple", Users.profile_name), tsquery)
            * 3.0
            + func.ts_rank(
                func.to_tsvector("simple", func.coalesce(Profiles.bio, "")), tsquery
            ),
        )
        base_query = base_query.order_by(desc(relevance_score))

    # ページネーション
    results = base_query.limit(limit).offset(offset).all()

    # 最新投稿を取得する場合
    if include_recent_posts and results:
        # クリエイターIDのリストを取得
        creator_ids = [r.id for r in results]

        # 各クリエイターの最新投稿4件を取得
        recent_posts_query = (
            db.query(
                Posts.id,
                Posts.creator_user_id,
                MediaAssets.storage_key.label("thumbnail_url"),
            )
            .join(MediaAssets, Posts.id == MediaAssets.post_id)
            .filter(Posts.creator_user_id.in_(creator_ids))
            .filter(Posts.deleted_at.is_(None))
            .filter(Posts.status == PostStatus.APPROVED, active_post_cond)
            .filter(MediaAssets.kind == MediaAssetKind.THUMBNAIL)
            .order_by(Posts.creator_user_id, desc(Posts.created_at))
        ).all()

        # クリエイターIDごとに最新投稿をグループ化
        posts_by_creator = {}
        for post in recent_posts_query:
            creator_id = str(post.creator_user_id)
            if creator_id not in posts_by_creator:
                posts_by_creator[creator_id] = []
            if len(posts_by_creator[creator_id]) < 5:
                posts_by_creator[creator_id].append(
                    {"id": str(post.id), "thumbnail_url": post.thumbnail_url}
                )

        # 結果に最新投稿を追加
        from collections import namedtuple

        # 元の結果フィールドにrecent_postsを追加
        CreatorWithPosts = namedtuple(
            "CreatorWithPosts",
            [
                "id",
                "profile_name",
                "username",
                "avatar_url",
                "bio",
                "followers_count",
                "is_verified",
                "posts_count",
                "recent_posts",
            ],
        )

        enhanced_results = []
        for r in results:
            enhanced_results.append(
                CreatorWithPosts(
                    id=r.id,
                    profile_name=r.profile_name,
                    username=r.username,
                    avatar_url=r.avatar_url,
                    bio=r.bio,
                    followers_count=r.followers_count,
                    is_verified=r.is_verified,
                    posts_count=r.posts_count,
                    recent_posts=posts_by_creator.get(str(r.id), []),
                )
            )

        return enhanced_results, total

    return results, total


def search_posts(
    db: Session,
    query: str,
    sort: str = "relevance",
    category_ids: Optional[List[str]] = None,
    post_type: Optional[int] = None,
    paid_only: bool = False,
    limit: int = 10,
    offset: int = 0,
) -> Tuple[List, int]:
    """
    投稿検索

    Args:
        db: データベースセッション
        query: 検索クエリ
        sort: ソート基準
        category_ids: カテゴリIDフィルター
        post_type: 投稿タイプフィルター (1=VIDEO, 2=IMAGE)
        paid_only: 単品販売のみ (price > 0)
        limit: 取得件数
        offset: オフセット

    Returns:
        (結果リスト, 総件数)
    """
    query_lower = query.lower().strip()
    tsquery = func.plainto_tsquery("simple", query)
    now = func.now()
    active_post_cond = and_(
        Posts.deleted_at.is_(None),
        Posts.status == PostStatus.APPROVED,
        or_(Posts.scheduled_at.is_(None), Posts.scheduled_at <= now),
        or_(Posts.expiration_at.is_(None), Posts.expiration_at > now),
    )
    # サブクエリでサムネイル取得
    from sqlalchemy import select

    thumbnail_subq = (
        select(MediaAssets.post_id, MediaAssets.storage_key)
        .where(MediaAssets.kind == MediaAssetKind.THUMBNAIL)
        .subquery()
    )

    # サブクエリで動画アセット(kind=4)のduration取得
    video_asset_subq = (
        select(MediaAssets.post_id, MediaAssets.duration_sec)
        .where(MediaAssets.kind == 4)
        .subquery()
    )

    # ベースクエリ
    base_query = (
        db.query(
            Posts.id,
            Posts.description,
            Posts.post_type,
            Posts.visibility,
            Posts.created_at,
            video_asset_subq.c.duration_sec.label("video_duration"),
            Users.id.label("creator_id"),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            thumbnail_subq.c.storage_key.label("thumbnail_key"),
            func.count(Likes.post_id).label("likes_count"),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .join(thumbnail_subq, Posts.id == thumbnail_subq.c.post_id)
        .outerjoin(video_asset_subq, Posts.id == video_asset_subq.c.post_id)
        .outerjoin(Likes, Posts.id == Likes.post_id)
    )

    # 単品販売フィルタ
    if paid_only:
        base_query = base_query.join(
            Prices, and_(Posts.id == Prices.post_id, Prices.is_active == True)
        )

    base_query = (
        base_query.filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(active_post_cond)
        .filter(Posts.visibility.in_([1, 2, 3]))  # 公開範囲
        .group_by(
            Posts.id,
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            thumbnail_subq.c.storage_key,
            video_asset_subq.c.duration_sec,
        )
    )

    # 検索条件 - Posts.descriptionのみに対して検索
    search_conditions = or_(
        func.to_tsvector("simple", func.coalesce(Posts.description, "")).op("@@")(
            tsquery
        ),
        Posts.description.ilike(f"%{query_lower}%"),  # 部分一致検索も追加
    )

    base_query = base_query.filter(search_conditions)

    # フィルター適用
    if category_ids:
        base_query = base_query.filter(
            Posts.id.in_(
                db.query(PostCategories.post_id).filter(
                    PostCategories.category_id.in_(category_ids)
                )
            )
        )

    if post_type:
        base_query = base_query.filter(Posts.post_type == post_type)

    # 総件数取得
    from sqlalchemy import select

    count_query = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_query).scalar()

    # ソート
    if sort == "popularity":
        base_query = base_query.order_by(desc("likes_count"))
    else:  # relevance
        relevance_score = (
            func.ts_rank(
                func.to_tsvector("simple", func.coalesce(Posts.description, "")),
                tsquery,
            )
            * 3.0
        )
        base_query = base_query.order_by(desc(relevance_score), desc(Posts.created_at))

    results = base_query.limit(limit).offset(offset).all()

    return results, total


def search_hashtags(
    db: Session, query: str, limit: int = 5, offset: int = 0
) -> Tuple[List, int]:
    """
    ハッシュタグ検索
    """
    query_lower = query.lstrip("#").lower().strip()
    tsquery = func.plainto_tsquery("simple", query_lower)

    # ベースクエリ
    base_query = (
        db.query(
            Tags.id,
            Tags.name,
            Tags.slug,
            func.count(PostTags.post_id).label("posts_count"),
        )
        .outerjoin(PostTags, Tags.id == PostTags.tag_id)
        .filter(
            or_(
                func.to_tsvector("simple", Tags.name).op("@@")(tsquery),
                Tags.name.ilike(f"%{query_lower}%"),
                Tags.slug.ilike(f"%{query_lower}%"),
            )
        )
        .group_by(Tags.id, Tags.name, Tags.slug)
        .order_by(desc("posts_count"))
    )

    # 総件数取得
    from sqlalchemy import select

    count_query = select(func.count()).select_from(base_query.subquery())
    total = db.execute(count_query).scalar()

    results = base_query.limit(limit).offset(offset).all()

    return results, total
