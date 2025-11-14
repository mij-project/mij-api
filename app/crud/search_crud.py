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
from app.constants.enums import PostStatus, AccountType, MediaAssetKind


def search_creators(
    db: Session,
    query: str,
    sort: str = "relevance",
    limit: int = 5,
    offset: int = 0
) -> Tuple[List, int]:
    """
    クリエイター検索

    Args:
        db: データベースセッション
        query: 検索クエリ
        sort: ソート基準 ('relevance' or 'popularity')
        limit: 取得件数
        offset: オフセット

    Returns:
        (結果リスト, 総件数)
    """
    # 検索クエリの前処理
    query_lower = query.lower().strip()
    tsquery = func.plainto_tsquery('simple', query)

    # ベースクエリ
    base_query = (
        db.query(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.bio,
            func.count(Follows.creator_user_id).label('followers_count'),
            Users.is_identity_verified.label('is_verified'),
            func.count(Posts.id).label('posts_count'),
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .outerjoin(Follows, Users.id == Follows.creator_user_id)
        .outerjoin(Posts, and_(
            Users.id == Posts.creator_user_id,
            Posts.deleted_at.is_(None),
            Posts.status == PostStatus.APPROVED
        ))
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
        func.to_tsvector('simple', Users.profile_name).op('@@')(tsquery),
        func.to_tsvector('simple', Profiles.username).op('@@')(tsquery),
        func.to_tsvector('simple', func.coalesce(Profiles.bio, '')).op('@@')(tsquery),
        Users.profile_name.ilike(f'{query_lower}%'),  # 前方一致
        Profiles.username.ilike(f'{query_lower}%'),
    )

    base_query = base_query.filter(search_conditions)

    # 総件数取得（サブクエリで効率化）
    from sqlalchemy import select
    count_query = select(func.count()).select_from(
        base_query.subquery()
    )
    total = db.execute(count_query).scalar()

    # ソート
    if sort == "popularity":
        base_query = base_query.order_by(desc('followers_count'))
    else:  # relevance
        # スコアリング: 完全一致 > 前方一致 > 部分一致
        relevance_score = case(
            (Users.profile_name.ilike(query_lower), 10.0),
            (Profiles.username.ilike(query_lower), 10.0),
            (Users.profile_name.ilike(f'{query_lower}%'), 5.0),
            (Profiles.username.ilike(f'{query_lower}%'), 5.0),
            else_=func.ts_rank(
                func.to_tsvector('simple', Users.profile_name),
                tsquery
            ) * 3.0 + func.ts_rank(
                func.to_tsvector('simple', func.coalesce(Profiles.bio, '')),
                tsquery
            )
        )
        base_query = base_query.order_by(desc(relevance_score))

    # ページネーション
    results = base_query.limit(limit).offset(offset).all()

    return results, total


def search_posts(
    db: Session,
    query: str,
    sort: str = "relevance",
    category_ids: Optional[List[str]] = None,
    post_type: Optional[int] = None,
    limit: int = 10,
    offset: int = 0
) -> Tuple[List, int]:
    """
    投稿検索

    Args:
        db: データベースセッション
        query: 検索クエリ
        sort: ソート基準
        category_ids: カテゴリIDフィルター
        post_type: 投稿タイプフィルター (1=VIDEO, 2=IMAGE)
        limit: 取得件数
        offset: オフセット

    Returns:
        (結果リスト, 総件数)
    """
    query_lower = query.lower().strip()
    tsquery = func.plainto_tsquery('simple', query)

    # ベースクエリ
    base_query = (
        db.query(
            Posts.id,
            Posts.description,
            Posts.post_type,
            Posts.visibility,
            Posts.created_at,
            Users.id.label('creator_id'),
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key.label('thumbnail_key'),
            func.count(Likes.post_id).label('likes_count'),
        )
        .join(Users, Posts.creator_user_id == Users.id)
        .join(Profiles, Users.id == Profiles.user_id)
        .join(MediaAssets, Posts.id == MediaAssets.post_id)
        .outerjoin(Likes, Posts.id == Likes.post_id)
        .filter(Posts.deleted_at.is_(None))
        .filter(Posts.status == PostStatus.APPROVED)
        .filter(Posts.visibility.in_([1, 2, 3]))  # 公開範囲
        .filter(MediaAssets.kind == MediaAssetKind.THUMBNAIL)
        .group_by(
            Posts.id,
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            MediaAssets.storage_key,
        )
    )

    # 検索条件 - Posts.descriptionのみに対して検索
    search_conditions = or_(
        func.to_tsvector('simple', func.coalesce(Posts.description, '')).op('@@')(tsquery),
        Posts.description.ilike(f'%{query_lower}%'),  # 部分一致検索も追加
    )

    base_query = base_query.filter(search_conditions)

    # フィルター適用
    if category_ids:
        base_query = base_query.filter(
            Posts.id.in_(
                db.query(PostCategories.post_id)
                .filter(PostCategories.category_id.in_(category_ids))
            )
        )

    if post_type:
        base_query = base_query.filter(Posts.post_type == post_type)

    # 総件数取得
    from sqlalchemy import select
    count_query = select(func.count()).select_from(
        base_query.subquery()
    )
    total = db.execute(count_query).scalar()

    # ソート
    if sort == "popularity":
        base_query = base_query.order_by(desc('likes_count'))
    else:  # relevance
        relevance_score = func.ts_rank(
            func.to_tsvector('simple', func.coalesce(Posts.description, '')),
            tsquery
        ) * 3.0
        base_query = base_query.order_by(desc(relevance_score), desc(Posts.created_at))

    results = base_query.limit(limit).offset(offset).all()

    return results, total


def search_hashtags(
    db: Session,
    query: str,
    limit: int = 5,
    offset: int = 0
) -> Tuple[List, int]:
    """
    ハッシュタグ検索
    """
    query_lower = query.lstrip('#').lower().strip()
    tsquery = func.plainto_tsquery('simple', query_lower)

    # ベースクエリ
    base_query = (
        db.query(
            Tags.id,
            Tags.name,
            Tags.slug,
            func.count(PostTags.post_id).label('posts_count'),
        )
        .outerjoin(PostTags, Tags.id == PostTags.tag_id)
        .filter(
            or_(
                func.to_tsvector('simple', Tags.name).op('@@')(tsquery),
                Tags.name.ilike(f'%{query_lower}%'),
                Tags.slug.ilike(f'%{query_lower}%'),
            )
        )
        .group_by(Tags.id, Tags.name, Tags.slug)
        .order_by(desc('posts_count'))
    )

    # 総件数取得
    from sqlalchemy import select
    count_query = select(func.count()).select_from(
        base_query.subquery()
    )
    total = db.execute(count_query).scalar()

    results = base_query.limit(limit).offset(offset).all()

    return results, total
