# app/schemas/user.py
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import List, Optional

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str

class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    class Config:
        from_attributes = True

class ProfilePostResponse(BaseModel):
    id: UUID
    likes_count: int
    created_at: datetime
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None

class ProfilePlanResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    price: int

class ProfilePurchaseResponse(BaseModel):
    id: UUID
    likes_count: int
    created_at: datetime
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    created_at: datetime

class ProfileGachaResponse(BaseModel):
    id: UUID
    amount: int
    created_at: datetime

class UserProfileResponse(BaseModel):
    id: UUID
    profile_name: str
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    bio: Optional[str] = None
    website_url: Optional[str] = None
    post_count: int
    follower_count: int
    posts: List[ProfilePostResponse]
    plans: List[ProfilePlanResponse]
    individual_purchases: List[ProfilePurchaseResponse]
    gacha_items: List[ProfileGachaResponse]
    
    class Config:
        from_attributes = True
