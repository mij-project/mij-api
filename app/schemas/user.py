# app/schemas/user.py
from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import List, Optional, Dict

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=20)

class EmailVerificationIn(BaseModel):
    email: EmailStr
    code: Optional[UUID] = None

class UserRegisterCompany(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=20)
    company_code: str

class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    class Config:
        from_attributes = True

class ProfilePostResponse(BaseModel):
    id: UUID
    post_type: int  # 1: 動画, 2: 画像
    likes_count: int
    created_at: datetime
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    video_duration: Optional[int] = None
    price: Optional[int] = None
    currency: Optional[str] = "JPY"
    is_reserved: Optional[bool] = False
    is_expired: Optional[bool] = False

class ProfilePlanResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    price: int
    currency: str = "JPY"
    type: Optional[int] = 1  # 1: 通常プラン, 2: おすすめプラン
    post_count: Optional[int] = 0
    plan_post: Optional[List[Dict[str, str]]] = []
    is_subscribed: Optional[bool] = False  # 現在のユーザーが加入済みかどうか

class ProfilePurchaseResponse(BaseModel):
    id: UUID
    likes_count: int
    created_at: datetime
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    video_duration: Optional[int] = None
    price: Optional[int] = None
    currency: Optional[str] = "JPY"
    is_reserved: Optional[bool] = False

class ProfileGachaResponse(BaseModel):
    id: UUID
    amount: int
    created_at: datetime

class UserProfileResponse(BaseModel):
    id: UUID
    profile_name: str
    username: Optional[str] = None
    offical_flg: Optional[bool] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    bio: Optional[str] = None
    links: Optional[dict] = None
    website_url: Optional[str] = None
    post_count: int
    follower_count: int
    posts: List[ProfilePostResponse]
    plans: List[ProfilePlanResponse]
    individual_purchases: List[ProfilePurchaseResponse]
    gacha_items: List[ProfileGachaResponse]

class UserOGPResponse(BaseModel):
    """ユーザーOGP情報レスポンス"""
    user_id: str
    profile_name: str
    username: str
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    cover_url: Optional[str] = None
    ogp_image_url: str
    
    class Config:
        from_attributes = True
