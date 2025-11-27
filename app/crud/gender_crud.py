from sqlalchemy.orm import Session
from app.models.gender import Gender
from typing import List, Union
from app.schemas.gender import GenderIDList, GenderSlugList

def get_genders(db: Session) -> List[Gender]:
    """
    性別一覧を取得

    Args:
        db (Session): データベースセッション

    Returns:
        List[Gender]: 性別一覧
    """
    genders = db.query(Gender).order_by(Gender.sort_order).filter(Gender.is_active == True).all()
    return genders

def get_gender_by_slug(db: Session, slug: Union[GenderSlugList, List[str]]) -> List[Gender]:
    """
    slugから性別IDを取得

    Args:
        db (Session): データベースセッション
        slug (Union[GenderSlugList, List[str]]): 性別スラッグリスト

    Returns:
        List[Gender]: 性別一覧
    """
    # slugがGenderSlugListオブジェクトの場合は.slug属性にアクセス、そうでなければ直接使用
    slug_list = slug.slug if hasattr(slug, 'slug') else slug
    genders = db.query(Gender).filter(Gender.slug.in_(slug_list)).all()
    return genders
