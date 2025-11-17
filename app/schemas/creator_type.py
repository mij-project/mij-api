from pydantic import BaseModel 
from typing import List

class CreatorTypeCreate(BaseModel):
    gender_slug_list: List[str]