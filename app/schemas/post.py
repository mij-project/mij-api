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
	official: bool
	creator_name: str
	username: str
	creator_avatar_url: Optional[str] = None
	duration: Optional[str] = None
	category_name: str
	is_time_sale: Optional[bool] = False

class PaginatedPostCategoryResponse(BaseModel):
	posts: List[PostCategoryResponse]
	total: int
	page: int
	per_page: int
	has_next: bool
	has_previous: bool
	category_name: str

class NewArrivalsResponse(BaseModel):
    id: str
    description: str
    thumbnail_url: Optional[str] = None
    creator_name: str
    username: str
    creator_avatar_url: Optional[str] = None
    duration: Optional[str] = None
    likes_count: int = 0
    is_time_sale: Optional[bool] = False

class PaginatedNewArrivalsResponse(BaseModel):
    posts: List[NewArrivalsResponse]
    page: int
    per_page: int
    has_next: bool
    has_previous: bool

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
	reject_comments: Optional[str] = None
	status: Optional[int] = None

class PostOGPCreatorResponse(BaseModel):
	"""投稿OGP用のクリエイター情報"""
	user_id: str
	profile_name: str
	username: str
	avatar_url: Optional[str] = None

class PostOGPResponse(BaseModel):
	"""投稿OGP情報レスポンス"""
	post_id: str
	title: str
	description: str
	post_type: int | None
	ogp_image_url: str
	creator: PostOGPCreatorResponse
	created_at: datetime