from pydantic import BaseModel
from typing import Optional
from uuid import UUID

class VerifyIn(BaseModel):
    token: str
    code: Optional[UUID] = None