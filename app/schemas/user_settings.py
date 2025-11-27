from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel
from enum import IntEnum

class UserSettingsType(IntEnum):
    EMAIL = 1

class UserSettingsResponse(BaseModel):
    id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    type: UserSettingsType
    settings: dict
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None