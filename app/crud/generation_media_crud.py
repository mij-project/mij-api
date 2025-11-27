# app/crud/generation_media_crud.py
"""
generation_media テーブル用のCRUD操作
"""
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
from app.models.generation_media import GenerationMedia
from app.constants.enums import GenerationMediaKind

def get_generation_media_by_post_id(db: Session, post_id: str) -> Optional[GenerationMedia]:
    """
    投稿IDに紐づくgeneration_mediaを取得

    Args:
        db: データベースセッション
        post_id: 投稿ID

    Returns:
        GenerationMedia | None: 生成メディアオブジェクト、存在しない場合はNone
    """
    return db.query(GenerationMedia).filter(
        GenerationMedia.post_id == post_id,
        GenerationMedia.kind == 2  # kind=2: 投稿画像
    ).first()


def get_generation_media_by_user_id(db: Session, user_id: str) -> Optional[GenerationMedia]:
    """
    ユーザーIDに紐づくgeneration_mediaを取得（プロフィールOGP）

    Args:
        db: データベースセッション
        user_id: ユーザーID

    Returns:
        GenerationMedia | None: 生成メディアオブジェクト、存在しない場合はNone
    """
    return db.query(GenerationMedia).filter(
        GenerationMedia.user_id == user_id,
        GenerationMedia.kind == 1  # kind=1: プロフィール画像
    ).first()


def create_generation_media(db: Session, data: dict) -> GenerationMedia:
    """
    generation_mediaレコードを作成

    Args:
        db: データベースセッション
        data: 作成データ
            - kind: int (1: プロフィール画像, 2: 投稿画像)
            - user_id: UUID (Optional)
            - post_id: UUID (Optional)
            - storage_key: str

    Returns:
        GenerationMedia: 作成された生成メディアオブジェクト
    """
    generation_media = GenerationMedia(
        kind=data.get("kind"),
        user_id=data.get("user_id"),
        post_id=data.get("post_id"),
        storage_key=data["storage_key"]
    )
    db.add(generation_media)
    db.flush()
    return generation_media


def upsert_generation_media_by_user(db: Session, user_id: str, storage_key: str) -> GenerationMedia:
    """
    ユーザーIDに紐づくgeneration_mediaを更新または作成（プロフィールOGP用）

    Args:
        db: データベースセッション
        user_id: ユーザーID
        storage_key: S3ストレージキー

    Returns:
        GenerationMedia: 更新/作成された生成メディアオブジェクト
    """
    # 既存レコードを検索
    existing = get_generation_media_by_user_id(db, user_id)

    if existing:
        # 更新
        existing.storage_key = storage_key
        db.flush()
        return existing
    else:
        # 新規作成
        data = {
            "kind": GenerationMediaKind.PROFILE_IMAGE,
            "user_id": user_id,
            "post_id": None,
            "storage_key": storage_key
        }
        return create_generation_media(db, data)
