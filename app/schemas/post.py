from pydantic import BaseModel, Field
from uuid import UUID
from typing import Optional, List
from datetime import datetime

class PostCreateRequest(BaseModel):
	post_id: Optional[UUID] = None
	description: str
	category_ids: List[str]
	tags: Optional[str] = None
	scheduled: bool
	formattedScheduledDateTime: Optional[str] = None
	expiration: bool
	expirationDate: Optional[datetime] = None
	plan: bool
	plan_ids: Optional[List[UUID]] = None
	single: bool
	price: Optional[int] = None
	post_type: str


class PostResponse(BaseModel):
	id: UUID

class PostCategoryResponse(BaseModel):
	id: UUID
	description: str
	thumbnail_url: Optional[str] = None
	likes_count: int
	creator_name: str
	username: str
	creator_avatar_url: Optional[str] = None

class NewArrivalsResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    duration: Optional[str] = None
    likes_count: int = 0

class PostUpdateRequest(BaseModel):
	post_id: UUID
	description: str
	category_ids: List[str]
	tags: Optional[str] = None
	scheduled: bool
	formattedScheduledDateTime: Optional[str] = None
	expiration: bool
	expirationDate: Optional[datetime] = None
	plan: bool
	plan_ids: Optional[List[UUID]] = None
	single: bool
	price: Optional[int] = None
	post_type: str