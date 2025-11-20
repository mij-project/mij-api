from sqlalchemy.orm import Session
from app.models.profiles import Profiles
from app.models.user import Users
from app.models.generation_media import GenerationMedia
from uuid import UUID
from app.schemas.account import AccountUpdateRequest
from datetime import datetime, timezone
from typing import Optional, Dict
from app.constants.enums import GenerationMediaKind
import os
CDN_BASE_URL = os.getenv("CDN_BASE_URL")

def create_profile(db: Session, user_id: UUID, username: str) -> Profiles:
    """
    プロフィールを作成
    """
    db_profile = Profiles(
        user_id=user_id,
        username=username,
    )
    db.add(db_profile)
    db.flush()
    return db_profile

def exist_profile_by_username(db: Session, username: str) -> bool:
    """
    ユーザー名に紐づくプロフィールが存在するかを確認
    
    Args:
        db (Session): データベースセッション
        username (str): ユーザー名
        
    Returns:
        bool: プロフィールが存在する場合はTrue、存在しない場合はFalse
    """
    return db.query(Profiles).filter(Profiles.username == username).first() is not None

def get_profile_by_user_id(db: Session, user_id: UUID) -> Profiles:
    """
    ユーザーIDに紐づくプロフィールを取得
    """
    return db.query(Profiles).filter(Profiles.user_id == user_id).first()

def get_profile_by_username(db: Session, username: str) -> Profiles:
    """
    ユーザー名に紐づくプロフィールを取得
    """
    return db.query(Profiles).filter(Profiles.username == username).first()

def get_profile_info_by_user_id(db: Session, user_id: UUID) -> Dict[str, Optional[str]]:
    """
    ユーザーIDに紐づくプロフィール情報を取得（profile_name, username, avatar_url, cover_url）
    """
    result = (
        db.query(
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(Users.id == user_id)
        .first()
    )

    if result:
        profile_name, username, avatar_url, cover_url = result
        return {
            "profile_name": profile_name,
            "username": username,
            "avatar_url": avatar_url if avatar_url else None,
            "cover_url": cover_url if cover_url else None
        }

def get_profile_edit_info_by_user_id(db: Session, user_id: UUID) -> Dict:
    """
    プロフィール編集用の情報を取得（profile_name, username, avatar_url, cover_url, bio, links）
    """
    result = (
        db.query(
            Users.profile_name,
            Profiles.username,
            Profiles.avatar_url,
            Profiles.cover_url,
            Profiles.bio,
            Profiles.links
        )
        .join(Profiles, Users.id == Profiles.user_id)
        .filter(Users.id == user_id)
        .first()
    )

    if result:
        profile_name, username, avatar_url, cover_url, bio, links = result
        return {
            "profile_name": profile_name,
            "username": username,
            "avatar_url": avatar_url,
            "cover_url": cover_url,
            "bio": bio,
            "links": links if links else {}
        }
    return None

def update_profile(db: Session, user_id: UUID, update_data: AccountUpdateRequest) -> Profiles:
    """
    プロフィールを更新
    """
    profile = get_profile_by_user_id(db, user_id)
    profile.username = update_data.username
    profile.bio = update_data.description
    profile.links = update_data.links
    if update_data.avatar_url is not None:
        profile.avatar_url = update_data.avatar_url
    if update_data.cover_url is not None:
        profile.cover_url = update_data.cover_url
    profile.updated_at = datetime.now(timezone.utc)
    db.add(profile)
    db.flush()
    return profile

def update_profile_by_x(db: Session, user_id: UUID, username: str):
    profile = db.query(Profiles).filter(Profiles.user_id == user_id).first()
    profile.username = username
    profile.updated_at = datetime.now(timezone.utc)
    db.add(profile)
    db.flush()
    return profile

def get_profile_ogp_image_url(db: Session, user_id: UUID) -> str | None:
    """
    ユーザーのOGP画像URLを取得
    優先順位: generation_media (kind=1) → カバー画像 → デフォルト画像
    """
    # デフォルトOGP画像URL
    frontend_url = os.getenv("FRONTEND_URL", "https://mijfans.jp")
    default_ogp_image = f"{frontend_url}/assets/mijfans.png"

    # 1. generation_mediaからOGP画像を取得（kind=1: プロフィール画像）
    generation_media = db.query(GenerationMedia).filter(
        GenerationMedia.user_id == user_id,
        GenerationMedia.kind == GenerationMediaKind.PROFILE_IMAGE
    ).first()

    if generation_media:
        return f"{CDN_BASE_URL}/{generation_media.storage_key}"

    # 2. profilesテーブルからカバー画像を取得
    profile = db.query(Profiles).filter(Profiles.user_id == user_id).first()

    if not profile:
        return default_ogp_image

    # カバー画像がある場合はそれを使用
    if profile.cover_url:
        return f"{CDN_BASE_URL}/{profile.cover_url}"

    # カバー画像がない場合はデフォルト画像
    return default_ogp_image

def get_profile_ogp_data(db: Session, user_id: UUID) -> Dict[str, Optional[str]] | None:
    """
    ユーザープロフィールのOGP生成に必要な全ての情報を取得

    Args:
        db: データベースセッション
        user_id: ユーザーID

    Returns:
        Dict: OGP情報（プロフィール詳細 + 統計情報 + OGP画像）
        None: ユーザーが見つからない場合
    """
    from app.models.posts import Posts
    from app.models.social import Follows

    # ユーザー情報 + プロフィール情報を取得
    result = (
        db.query(
            Users.id,
            Users.profile_name,
            Profiles.username,
            Profiles.bio,
            Profiles.avatar_url,
            Profiles.cover_url
        )
        .outerjoin(Profiles, Users.id == Profiles.user_id)
        .filter(Users.id == user_id)
        .first()
    )

    if not result:
        return None


    # OGP画像URLを取得（generation_media優先）
    ogp_image_url = get_profile_ogp_image_url(db, user_id)

    # アバターURL
    avatar_url = None
    if result.avatar_url:
        avatar_url = f"{CDN_BASE_URL}/{result.avatar_url}"

    # カバーURL
    cover_url = None
    if result.cover_url:
        cover_url = f"{CDN_BASE_URL}/{result.cover_url}"

    return {
        "user_id": str(result.id),
        "profile_name": result.profile_name or "ユーザー",
        "username": result.username or "",
        "bio": result.bio,
        "avatar_url": avatar_url,
        "cover_url": cover_url,
        "ogp_image_url": ogp_image_url,
    }
