from pydantic import BaseModel
from uuid import UUID
from typing import List

class CategoryOut(BaseModel):
    id: UUID
    slug: str
    name: str
    genre_id: UUID

class GenreOut(BaseModel):
    id: UUID
    slug: str
    name: str

class GenreWithCategoriesOut(BaseModel):
    id: UUID
    slug: str
    name: str
    categories: List[CategoryOut]
