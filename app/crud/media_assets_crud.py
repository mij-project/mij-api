from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.media_assets import MediaAssets
from app.models.posts import Posts
from app.constants.enums import MediaAssetKind
from app.constants.enums import PostType
from typing import List

def create_media_asset(db: Session, media_asset_data: dict) -> MediaAssets:
    """
    メディアアセット作成

    Args:
        db (Session): データベースセッション
        media_asset (MediaAssets): メディアアセット

    Returns:
        MediaAssets: メディアアセット
    """
    db_media_asset = MediaAssets(**media_asset_data)
    db.add(db_media_asset)
    db.flush()
    return db_media_asset

def get_media_asset_by_post_id(db: Session, post_id: str, type: str) -> MediaAssets:
    """
    メディアアセット取得（postテーブルとJOINしてユーザーIDも取得）

    Args:
        db (Session): データベースセッション
        post_id (str): 投稿ID

    Returns:
        MediaAssets: メディアアセット（post情報も含む）
    """

    if type == PostType.VIDEO:
        kind = [
            MediaAssetKind.MAIN_VIDEO, 
            MediaAssetKind.SAMPLE_VIDEO, 
        ]
    else:
        kind = [
            MediaAssetKind.IMAGES, 
        ]

    result = db.execute(
        select(
            MediaAssets.id,
            MediaAssets.post_id,
            MediaAssets.kind,
            MediaAssets.created_at,
            MediaAssets.storage_key,
            MediaAssets.mime_type,
            Posts.creator_user_id
        ).join(
            Posts, MediaAssets.post_id == Posts.id
        ).where(
            MediaAssets.post_id == post_id, 
            MediaAssets.kind.in_(kind)
        )
    ).all()
    
    return result

def get_media_asset_by_id(db: Session, asset_id: str) -> MediaAssets:
    """
    メディアアセット取得
    """
    return db.query(MediaAssets).filter(MediaAssets.id == asset_id).first()

def get_media_assets_by_ids(db: Session, asset_ids: List[str], type: str) -> List[MediaAssets]:
    """
    メディアアセット取得（asset_idsが一致するものを返す）
    """
    
    if type == 'video':
        kind = [
            MediaAssetKind.MAIN_VIDEO, 
            MediaAssetKind.SAMPLE_VIDEO, 
        ]
    else:
        kind = [
            MediaAssetKind.IMAGES, 
        ]
    return (
        db.query(
            MediaAssets.id,
            MediaAssets.post_id,
            MediaAssets.kind,
            MediaAssets.created_at,
            MediaAssets.storage_key,
            MediaAssets.mime_type,
            Posts.creator_user_id
        )
        .filter(MediaAssets.id.in_(asset_ids), MediaAssets.kind.in_(kind))
        .join(Posts, MediaAssets.post_id == Posts.id)
        .all())

def update_media_asset(db: Session, asset_id: str, update_data: dict) -> MediaAssets:
    """
    メディアアセット更新
    """
    # 辞書を直接渡して更新
    db.query(MediaAssets).filter(MediaAssets.id == asset_id).update(update_data)
    db.flush()
    
    # 更新されたオブジェクトを取得して返す
    return db.query(MediaAssets).filter(MediaAssets.id == asset_id).first()

def update_sub_media_assets_status(db: Session,post_id: str, kind: List[str], status: int) -> MediaAssets:
    """
    メディアアセット更新（post_idとkindが一致するものを更新）
    """
    db.query(MediaAssets).filter(MediaAssets.post_id == post_id, MediaAssets.kind.in_(kind)).update({"status": status})
    db.flush()
    db.commit()
    return db.query(MediaAssets).filter(MediaAssets.post_id == post_id, MediaAssets.kind.in_(kind)).all()

def get_media_assets_by_post_id(db: Session, post_id: str, kind: str) -> str:
    """
    メディアアセット取得（最新のものを返す）

    Args:
        db (Session): データベースセッション
        post_id (str): 投稿ID
        kind (str): メディアアセットの種類

    Returns:
        MediaAssets: メディアアセット（最新のもの）
    """
    return (
        db.query(
            MediaAssets.storage_key,
            MediaAssets.id
        )
        .filter(MediaAssets.post_id == post_id, MediaAssets.kind == kind)
        .order_by(MediaAssets.created_at.desc())
        .first()
    )

def get_media_assets_by_post_id_and_kind(db: Session, post_id: str, kind: str) -> MediaAssets:
    """
    メディアアセット取得（post_idとkindが一致するものを返す）
    """
    return (
        db.query(MediaAssets)
        .filter(MediaAssets.post_id == post_id, MediaAssets.kind == kind)
        .order_by(MediaAssets.created_at.desc())
        .first()
    )

def delete_media_asset(db: Session, asset_id: str) -> bool:
    """
    メディアアセット削除
    """
    asset = db.query(MediaAssets).filter(MediaAssets.id == asset_id).first()
    if asset:
        db.delete(asset)
        db.commit()
        return True
    return False

def get_all_media_assets_by_post_id_and_kind(db: Session, post_id: str, kind: str) -> list[MediaAssets]:
    """
    指定されたpost_idとkindに一致するすべてのメディアアセットを取得

    Args:
        db (Session): データベースセッション
        post_id (str): 投稿ID
        kind (str): メディアアセットの種類

    Returns:
        list[MediaAssets]: メディアアセット一覧
    """
    return (
        db.query(MediaAssets)
        .filter(MediaAssets.post_id == post_id, MediaAssets.kind == kind)
        .order_by(MediaAssets.created_at.asc())
        .all()
    )