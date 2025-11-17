from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.deps.auth import get_current_user
from app.models.user import Users
from app.db.base import get_db
from app.schemas.gender import GenderOut, GenderSlugList
from typing import List
from app.crud.gender_crud import get_genders, get_gender_by_slug
from app.crud.creator_type_crud import create_creator_type, delete_creator_type_by_user_id
from app.models.creator_type import CreatorType
from app.schemas.creator_type import CreatorTypeCreate
router = APIRouter()

@router.get("/", response_model=List[GenderOut])
def get_genders_api(db: Session = Depends(get_db)):
    """
    性別一覧を取得
    
    Args:
        db (Session): データベースセッション

    Returns:
        List[GenderOut]: 性別一覧
    """
    try:
        genders = get_genders(db)
        return [GenderOut(slug=gender.slug, name=gender.name) for gender in genders]
    except Exception as e:
        print("性別一覧取得エラー: ", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
def create_gender_for_creator(
    creator_type_create: CreatorTypeCreate, 
    db: Session = Depends(get_db),
    user: Users = Depends(get_current_user)
):
    """クリエイターの性別を作成

    Args:
        gender_slug_list (GenderSlugList): 性別スラッグリスト
        db (Session): データベースセッション
        user (Users): ユーザー

    Returns:
        dict: 性別作成結果
    """
    try:
        delete_creator_type_by_user_id(db, user.id)

        for gender_slug in creator_type_create.gender_slug_list:
            create_creator_type(db, CreatorType(user_id=user.id, gender_id=gender_slug))

        return {"result": "true"}            
    except Exception as e:
        print("性別作成エラー: ", e)
        db.rollback()
        return {"result": "性別作成失敗", "error": str(e)}