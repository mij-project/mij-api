from typing import List, Optional
from pydantic import BaseModel, Field, model_validator
from enum import IntEnum
from uuid import UUID
from datetime import datetime

#Payload
class NotificationPayloadAdmin(BaseModel):
  title: str = Field(..., description='通知タイトル')
  subtitle: str = Field(..., description='通知サブタイトル')
  message: str = Field(..., description='通知内容')
  users: Optional[List[str]] = Field(default=[], description='ユーザーID')

class NotificationPayloadUsers(BaseModel):
  title: str = Field(..., description='通知タイトル')
  subtitle: str = Field(..., description='通知サブタイトル')
  avatar: Optional[str] = Field(None, description='アバターURL')
  redirect_url: Optional[str] = Field(None, description='転送URL')

class NotificationPayloadPayments(BaseModel):
  title: str = Field(..., description='通知タイトル')
  subtitle: str = Field(..., description='通知サブタイトル')
  avatar: Optional[str] = Field(None, description='アバターURL')
  redirect_url: Optional[str] = Field(None, description='転送URL')

class NotificationType(IntEnum):
  ADMIN = 1 # admin -> users, can create by admin in admin screen
  USERS = 2 # users -> users, can create by users in app when users follow each other, like, comment, etc.
  PAYMENTS = 3 # payments -> users, can create by payments in app when users pay for the content, subscription, etc.

class NotificationCreateRequest(BaseModel):
  type: NotificationType = Field(..., description='通知種別: 1: admin -> users 2: users -> users 3: payments')
  payload: dict = Field(..., description='通知内容: 通知内容をJSON形式で指定')
  @model_validator(mode='after')
  def validate_payload_by_type(self):
    if self.type == NotificationType.ADMIN:
      NotificationPayloadAdmin(**self.payload)
    elif self.type == NotificationType.USERS:
      NotificationPayloadUsers(**self.payload)
    elif self.type == NotificationType.PAYMENTS:
      NotificationPayloadPayments(**self.payload)
    else:
      raise ValueError('Invalid notification type')
    return self

class NotificationCreateResponse(BaseModel):
  id: UUID = Field(..., description='通知ID')
  type: NotificationType = Field(..., description='通知種別: 1: admin -> users 2: users -> users 3: payments')
  payload: dict = Field(..., description='通知内容: 通知内容をJSON形式で指定')
  is_read: bool = Field(..., description='既読フラグ')
  read_at: Optional[datetime] = Field(None, description='既読日時')
  created_at: datetime = Field(..., description='作成日時')
  updated_at: datetime = Field(..., description='更新日時')

class PaginatedNotificationAdminResponse(BaseModel):
  notifications: List[NotificationCreateResponse] = Field(..., description='通知一覧')
  total: int = Field(..., description='総件数')
  page: int = Field(..., description='ページ番号')
  limit: int = Field(..., description='1ページあたりの件数')
  total_pages: int = Field(..., description='総ページ数')


class PaginatedNotificationUserResponse(BaseModel):
  notifications: List[NotificationCreateResponse] = Field(..., description='通知一覧')
  total: int = Field(..., description='総件数')
  page: int = Field(..., description='ページ番号')
  total_pages: int = Field(..., description='総ページ数')
  has_next: bool = Field(..., description='次のページが存在するかどうか')
  
class MarkNotificationAsReadRequest(BaseModel):
  notification_id: str = Field(..., description='通知ID')
  user_id: str = Field(..., description='ユーザーID')
  type: NotificationType = Field(..., description='通知種別: 1: admin -> users 2: users -> users 3: payments')

class GetUnreadCountResponse(BaseModel):
  admin: int = Field(..., description='管理者用の未読通知数')
  users: int = Field(..., description='ユーザー用の未読通知数')
  payments: int = Field(..., description='支払い用の未読通知数')