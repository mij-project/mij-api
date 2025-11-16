from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING
from uuid import uuid4, UUID
from datetime import datetime

from sqlalchemy import ForeignKey, Text, SmallInteger, Boolean, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, CITEXT
from sqlalchemy.orm import relationship, Mapped, mapped_column

from app.db.base import Base

if TYPE_CHECKING:
    from .profiles import Profiles
    from .creators import Creators
    from .posts import Posts
    from .plans import Plans
    from .subscriptions import Subscriptions
    from .orders import Orders
    from .creator_type import CreatorType
    from .gender import Gender
    from .email_verification_tokens import EmailVerificationTokens
    from .conversation_messages import ConversationMessages
    from .conversation_participants import ConversationParticipants
    from .sms_verifications import SMSVerifications
    from .banners import Banners
    from .events import UserEvents
    from .companies import CompanyUsers

class Users(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    profile_name: Mapped[Optional[str]] = mapped_column(CITEXT, unique=True, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(CITEXT, unique=True, nullable=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    is_phone_verified: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    is_identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    phone_verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    identity_verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    offical_flg: Mapped[bool] = mapped_column(Boolean, nullable=True, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    
    profile: Mapped[Optional["Profiles"]] = relationship("Profiles", back_populates="user", uselist=False)
    creator: Mapped[Optional["Creators"]] = relationship("Creators", back_populates="user", uselist=False)
    posts: Mapped[List["Posts"]] = relationship("Posts", back_populates="creator")
    plans: Mapped[List["Plans"]] = relationship("Plans", back_populates="creator")
    subscriptions: Mapped[List["Subscriptions"]] = relationship("Subscriptions", back_populates="user")
    orders: Mapped[List["Orders"]] = relationship("Orders", back_populates="user")
    creator_type: Mapped[List["CreatorType"]] = relationship("CreatorType", back_populates="user", cascade="all, delete-orphan", passive_deletes=True, lazy="selectin")
    genders: Mapped[List["Gender"]] = relationship("Gender", secondary="creator_type", viewonly=True, lazy="selectin")
    email_verification_tokens: Mapped[List["EmailVerificationTokens"]] = relationship("EmailVerificationTokens", back_populates="user")
    conversations: Mapped[List["ConversationMessages"]] = relationship("ConversationMessages", back_populates="sender_user", foreign_keys="ConversationMessages.sender_user_id")
    participants: Mapped[List["ConversationParticipants"]] = relationship("ConversationParticipants", back_populates="user")
    sms_verifications: Mapped[List["SMSVerifications"]] = relationship("SMSVerifications", back_populates="user")
    banners: Mapped[List["Banners"]] = relationship("Banners", back_populates="creator")
    user_events: Mapped[List["UserEvents"]] = relationship("UserEvents", back_populates="user")
    company_users: Mapped[List["CompanyUsers"]] = relationship("CompanyUsers", back_populates="user")