from pydantic import BaseModel, Field
from typing import Optional

class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1)
    auth: str = Field(min_length=1)

class PushSubscription(BaseModel):
    endpoint: str
    keys: PushKeys

class SubscribePushNotificationRequest(BaseModel):
    subscription: PushSubscription
    platform: Optional[str] = None

class PushSubscriptionForUnsubscribe(BaseModel):
    endpoint: str

class UnsubscribePushNotificationRequest(BaseModel):
    subscription: PushSubscriptionForUnsubscribe

class PushSubscriptionForUpdate(BaseModel):
    endpoint: str

class UpdateSubscribePushNotificationRequest(BaseModel):
    subscription: PushSubscriptionForUpdate