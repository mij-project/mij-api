from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.crud.creator_type_crud import get_creator_type_by_user_id
from app.models.creator_type import CreatorType
from app.models.user import Users
from app.deps.auth import get_current_user
from app.crud.creator_type_crud import create_creator_type, delete_creator_type_by_user_id
from app.schemas.creator_type import CreatorTypeCreate
from typing import List
from app.models.gender import Gender
from app.core.logger import Logger

logger = Logger.get_logger()
router = APIRouter()

@router.get("/", response_model=List[str])
def get_creator_type_by_user_id_api(db: Session = Depends(get_db), user: Users = Depends(get_current_user)):
    try:
        creator_type = get_creator_type_by_user_id(db, user.id)
        return creator_type
    except Exception as e:
        logger.error("クリエイタータイプ取得エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
def create_creator_type_api(creator_type_create: CreatorTypeCreate, db: Session = Depends(get_db), user: Users = Depends(get_current_user)):

    """クリエイタータイプを作成

    Args:
        creator_type (CreatorType): クリエイタータイプ
        db (Session): データベースセッション
        user (Users): ユーザー

    Returns:
        dict: クリエイタータイプ作成結果
    """
    try:
        delete_creator_type_by_user_id(db, user.id)
        if not creator_type_create.gender_slug_list:
            return {"result": "true"}

        # slug -> id へのマッピングを取得
        genders = (
            db.query(Gender.id, Gender.slug)
            .filter(Gender.slug.in_(creator_type_create.gender_slug_list))
            .all()
        )
        slug_to_id = {slug: gid for (gid, slug) in genders}

        # 指定された slug のうち存在しないものがあれば 400
        not_found_slugs = [
            slug for slug in creator_type_create.gender_slug_list if slug not in slug_to_id
        ]
        if not_found_slugs:
            raise HTTPException(status_code=400, detail=f"Invalid gender slug(s): {', '.join(not_found_slugs)}")

        for gender_slug in creator_type_create.gender_slug_list:
            create_creator_type(db, CreatorType(user_id=user.id, gender_id=slug_to_id[gender_slug]))
        return {"result": "true"}
    except Exception as e:
        logger.error("クリエイタータイプ作成エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))