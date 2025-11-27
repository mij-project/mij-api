from pydantic import BaseModel
from typing import List
from uuid import UUID
from datetime import datetime
from typing import Optional

class OrderCreateRequest(BaseModel):
    item_type: int
    price_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None