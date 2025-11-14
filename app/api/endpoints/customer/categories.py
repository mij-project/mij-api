from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.base import get_db
from app.schemas.categories import CategoryOut, GenreOut, GenreWithCategoriesOut
from app.crud.categories_crud import get_categories, get_genres, get_recommended_categories, get_recently_used_categories, get_genres_with_categories
from app.deps.auth import get_current_user
from typing import List

router = APIRouter()

@router.get("/genres", response_model=List[GenreOut])
def get_genres_api(db: Session = Depends(get_db)):
    try:
        genres = get_genres(db)
        return [GenreOut(id=genre.id, slug=genre.slug, name=genre.name) for genre in genres]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/categories", response_model=List[CategoryOut])
def get_categories_api(db: Session = Depends(get_db)):
    try:
        categories = get_categories(db)
        return [CategoryOut(id=category.id, slug=category.slug, name=category.name, genre_id=category.genre_id) for category in categories]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recommended", response_model=List[CategoryOut])
def get_recommended_categories_api(db: Session = Depends(get_db)):
    try:
        categories = get_recommended_categories(db)
        return [CategoryOut(id=category.id, slug=category.slug, name=category.name, genre_id=category.genre_id) for category in categories]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/recent", response_model=List[CategoryOut])
def get_recent_categories_api(current_user = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        categories = get_recently_used_categories(db, current_user.id)
        return [CategoryOut(id=category.id, slug=category.slug, name=category.name, genre_id=category.genre_id) for category in categories]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/genres-with-categories", response_model=List[GenreWithCategoriesOut])
def get_genres_with_categories_api(db: Session = Depends(get_db)):
    try:
        genres_data = get_genres_with_categories(db)
        return [
            GenreWithCategoriesOut(
                id=item["genre"].id,
                slug=item["genre"].slug,
                name=item["genre"].name,
                categories=[
                    CategoryOut(
                        id=cat.id,
                        slug=cat.slug,
                        name=cat.name,
                        genre_id=cat.genre_id
                    ) for cat in item["categories"]
                ]
            ) for item in genres_data
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
