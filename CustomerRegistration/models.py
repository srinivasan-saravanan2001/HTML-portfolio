from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel

class KidRegistration(BaseModel):
    id: Optional[str] = None
    kids_name: str
    parent_name: str
    kids_age: str
    school: str
    location: str
    phone_raw_or_hash: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    column1: Optional[str] = None
    column2: Optional[str] = None
    column3: Optional[str] = None
    column4: Optional[str] = None
    column5: Optional[str] = None
    event_name: Optional[str] = None
    event_location: Optional[str] = None        # ← Added
    confirmed_date: Optional[datetime] = None   # ← Added

class KidRegistrationUpdate(BaseModel):
    kids_name: Optional[str] = None
    parent_name: Optional[str] = None
    kids_age: Optional[str] = None
    school: Optional[str] = None
    location: Optional[str] = None
    phone_raw_or_hash: Optional[str] = None
    is_active: Optional[bool] = None
    column1: Optional[str] = None
    column2: Optional[str] = None
    column3: Optional[str] = None
    column4: Optional[str] = None
    column5: Optional[str] = None
    event_name: Optional[str] = None
    event_location: Optional[str] = None        # ← Added
    confirmed_date: Optional[datetime] = None   # ← Added


class KidRegistrationEventUpdate(BaseModel):
    event_location: Optional[str] = None
    confirmed_date: Optional[datetime] = None

    class Config:
        extra = "forbid"   # Prevents sending any other fields accidentally